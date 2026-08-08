"""M1 eval harness: execute AGR graphs against a runner and verify contracts.

The interpreter is real (routers, joins, bounded loops, verification asserts).
Runners are pluggable: MockRunner replays golden fixtures (measures graph/contract
mechanics), LLMRunner calls any OpenAI-compatible endpoint (measures model quality).
Every profile records which runner produced it — mock results are marked provisional.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import urllib.request
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field

_ORDER = {"trivial": -1, "low": 0, "simple": 0, "medium": 1, "moderate": 1,
          "high": 2, "complex": 2, "critical": 3}


class Level:
    """Ordered qualitative literal so conditions like `risk >= medium` evaluate."""

    def __init__(self, s: str):
        self.s, self.v = s, _ORDER[s]

    def _v(self, o):
        return o.v if isinstance(o, Level) else _ORDER.get(o)

    def __eq__(self, o):  # noqa: D105
        return self._v(o) == self.v

    def __le__(self, o):
        return self.v <= self._v(o)

    def __lt__(self, o):
        return self.v < self._v(o)

    def __ge__(self, o):
        return self.v >= self._v(o)

    def __gt__(self, o):
        return self.v > self._v(o)

    def __hash__(self):
        return hash(self.v)

    def __repr__(self):
        return f"Level({self.s})"


class DotDict(dict):
    """dict with attribute access, so asserts can say `output.verdict`."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e


def wrap(v):
    if isinstance(v, dict):
        return DotDict({k: wrap(x) for k, x in v.items()})
    if isinstance(v, list):
        return [wrap(x) for x in v]
    return v


_SAFE = {"len": len, "all": all, "any": any, "sum": sum, "min": min, "max": max,
         "abs": abs, "round": round, "true": True, "false": False, "null": None,
         **{name: Level(name) for name in _ORDER}}


def safe_eval(expr: str, bb: dict):
    ns = {**_SAFE, **wrap(dict(bb))}
    return eval(expr, {"__builtins__": {}}, ns)  # noqa: S307 — namespace is closed


def edge_true(when: str | None, bb: dict) -> bool:
    if not when:
        return True
    try:
        return bool(safe_eval(when, bb))
    except Exception:
        return False  # unresolvable condition = edge not taken


class HumanGateRequired(Exception):
    """A `kind: human` node was reached with no authority to approve it.

    Raised by LLMRunner: a model must not sign its own approval gate. Pass
    auto_approve=True (CI only) to bypass — the report is stamped accordingly
    and the resulting profile is not authoritative.
    """


@dataclass
class RunReport:
    trace: list[str] = field(default_factory=list)
    steps: int = 0
    assert_failures: list[str] = field(default_factory=list)
    skipped_commands: int = 0
    commands_run: int = 0
    command_failures: list[str] = field(default_factory=list)
    hit_step_cap: bool = False
    # v1.1
    deadlocked: bool = False
    auto_approved: bool = False
    approvals: list[tuple[str, bool]] = field(default_factory=list)
    retries_used: int = 0
    expanded: bool = False

    @property
    def rejected_approvals(self) -> list[str]:
        return [nid for nid, ok in self.approvals if not ok]

    @property
    def passed(self) -> bool:
        return (not self.assert_failures and not self.command_failures
                and not self.hit_step_cap and not self.deadlocked)


class MockRunner:
    """Replays per-node fixture outputs; a list means successive visits."""

    name = "mock"

    def __init__(self, node_outputs: dict):
        self.node_outputs, self.visits = node_outputs, defaultdict(int)

    def run(self, node: dict, bb: dict) -> dict:
        out = self.node_outputs.get(node["id"], {})
        if isinstance(out, list):
            out = out[min(self.visits[node["id"]], len(out) - 1)]
        self.visits[node["id"]] += 1
        return deepcopy(out)


class LLMRunner:
    """Live runner against any OpenAI-compatible endpoint (env-configured)."""

    def __init__(self):
        self.base = os.environ["AGR_LLM_BASE_URL"].rstrip("/")
        self.model = os.environ["AGR_LLM_MODEL"]
        self.key = os.environ.get("AGR_LLM_API_KEY", "")
        self.name = f"llm:{self.model}"

    def run(self, node: dict, bb: dict) -> dict:
        prompt = (
            f"You are node '{node['id']}' (speciality: {node['speciality']}) in a workflow. "
            f"Abilities: {', '.join(node.get('abilities', []))}. Blackboard: {json.dumps(bb, default=str)}. "
            "Reply with ONLY a JSON object of your output keys."
        )
        req = urllib.request.Request(
            f"{self.base}/chat/completions",
            data=json.dumps({"model": self.model,
                             "messages": [{"role": "user", "content": prompt}]}).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.key}"} if self.key else {})},
        )
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
            text = json.load(r)["choices"][0]["message"]["content"]
        return json.loads(text[text.index("{"): text.rindex("}") + 1])

    def approve(self, node: dict, bb: dict, auto_approve: bool = False) -> dict:
        """Refuse to sign a human gate — a model must not approve its own work.

        `auto_approve` exists for CI only; the run report is stamped
        `auto_approved` so the resulting profile is never mistaken for a real
        sign-off.
        """
        if not auto_approve:
            raise HumanGateRequired(
                f"node '{node['id']}' is a human approval gate "
                f"(contract: {node['approval']['contract']}). "
                "Re-run with --auto-approve to bypass in CI, or supply an approving runner."
            )
        return {"signed_off": True, "approver": "auto-approve", "auto_approved": True}


def _normalize(doc: dict) -> dict:
    """Desugar v1.1 `on_error: <node>` into an explicit error edge."""
    extra = [
        {"from": n["id"], "to": n["on_error"], "kind": "error"}
        for n in doc["nodes"]
        if n.get("on_error")
    ]
    if not extra:
        return doc
    out = dict(doc)
    out["edges"] = list(doc["edges"]) + extra
    return out


def _quorum_n(join: str) -> int | None:
    if join.startswith("quorum(") and join.endswith(")"):
        return int(join[7:-1])
    return None


class _Readiness:
    """Evaluates join rules against edge resolution and dead-branch settlement.

    Only *forward flow* edges count toward a join. Back-edges (retry loops) and
    compensate edges are excluded — a retry edge is by construction unresolved
    on the first pass, so counting it would deadlock every `all` join.

    The subtle case is a predecessor that will never run: when a router picks
    one branch, the other branch's node never executes, so its outgoing edge
    never *resolves*. A naive `all` would wait forever. Such an edge is instead
    **settled**: its source is provably dead (not queued, never ran, and every
    one of its own incoming edges settled without being taken). Settlement
    recurses up the graph, with a visit guard for cycles.
    """

    def __init__(self, doc, nodes, in_flow, resolved, taken, ran, pending, forced):
        self.edges, self.nodes, self.in_flow = doc["edges"], nodes, in_flow
        self.resolved, self.taken, self.ran, self.pending = resolved, taken, ran, pending
        # Nodes pulled in by a taken error/compensate edge. These are off the
        # forward-flow graph entirely, so no join rule can vouch for them —
        # being routed to by an exceptional path IS their readiness condition.
        self.forced = forced

    def _dead(self, nid: str, seen: frozenset) -> bool:
        if nid in self.ran or nid in self.pending or nid in seen:
            return False
        incoming = self.in_flow.get(nid, [])
        if not incoming:
            return False  # an entry node that simply hasn't been reached yet
        seen = seen | {nid}
        return all(self.settled(i, seen) for i in incoming) and not any(
            i in self.taken for i in incoming
        )

    def settled(self, i: int, seen: frozenset = frozenset()) -> bool:
        """Edge i will never change state: its source ran, or can never run."""
        return i in self.resolved or self._dead(self.edges[i]["from"], seen)

    def ready(self, nid: str) -> bool:
        if nid in self.forced:
            return True
        incoming = self.in_flow.get(nid, [])
        if not incoming:
            return True  # entry node
        join = self.nodes[nid].get("join", "any")
        n_taken = sum(1 for i in incoming if i in self.taken)
        if join == "all":
            return all(self.settled(i) for i in incoming) and n_taken >= 1
        q = _quorum_n(join)
        if q is not None:
            return n_taken >= q
        return n_taken >= 1  # "any" — v1 behavior


def _run_command(cmd: str, cwd, rep: RunReport) -> None:
    """Execute a `verification[].command` and record its exit status.

    Opt-in only. A verification command runs real code on the real machine, so
    the default stays `skipped` — counted and reported, never silently treated
    as passing.
    """
    try:
        proc = subprocess.run(  # noqa: S603 — command is authored in the graph, opt-in by the caller
            shlex.split(cmd), cwd=cwd, capture_output=True, text=True, timeout=300, check=False
        )
    except (OSError, subprocess.SubprocessError) as ex:
        rep.command_failures.append(f"{cmd} ({type(ex).__name__}: {ex})")
        return
    rep.commands_run += 1
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        rep.command_failures.append(f"{cmd} (exit {proc.returncode}: {tail[0]})")


def run_graph(doc: dict, runner, root=None, auto_approve: bool = False,
              run_commands: bool = False) -> RunReport:
    """Execute an AGR graph against a runner.

    v1.1 adds: subgraph expansion, join semantics, error/compensate edge kinds,
    per-node retries, and human approval gates. With every node defaulting to
    `join: any` and no v1.1 fields present, scheduling is byte-identical to v1 —
    locked by tests/fixtures/v1_trace_lock.json.
    """
    from .subgraphs import entry_nodes, expand, has_subgraphs  # local: avoids an import cycle

    rep = RunReport()
    if has_subgraphs(doc):
        doc = expand(doc, root) if root else expand(doc)
        rep.expanded = True
    doc = _normalize(doc)

    nodes = {n["id"]: n for n in doc["nodes"]}
    order = {n["id"]: i for i, n in enumerate(doc["nodes"])}
    out_edges: dict[str, list[int]] = defaultdict(list)
    in_flow: dict[str, list[int]] = defaultdict(list)
    for i, e in enumerate(doc["edges"]):
        out_edges[e["from"]].append(i)
        kind = e.get("kind", "flow")
        is_back = order.get(e["to"], 0) <= order.get(e["from"], -1)
        if kind == "flow" and not is_back:
            in_flow[e["to"]].append(i)

    # One shared definition of "entry" across harness, linter and compose.
    # Conditionally-reached nodes land in the initial frontier but are gated by
    # their join rule, so a branch the router did not pick never executes.
    pending = list(entry_nodes(doc))

    resolved: set[int] = set()
    taken: set[int] = set()
    ran: set[str] = set()
    forced: set[str] = set()
    visits: dict[str, int] = defaultdict(int)
    attempts: dict[str, int] = defaultdict(int)
    bb: dict = {}
    cap = doc["termination"]["max_steps"]
    rdy = _Readiness(doc, nodes, in_flow, resolved, taken, ran, pending, forced)

    while pending:
        if rep.steps >= cap:
            rep.hit_step_cap = True
            break
        pick = next((i for i, nid in enumerate(pending) if rdy.ready(nid)), None)
        if pick is None:
            # Nothing is ready. Distinguish two cases: a node whose incoming
            # edges are all settled but unsatisfying is a *dead branch* (the
            # router chose elsewhere) and is simply dropped; a node still
            # waiting on something that could still happen is a real deadlock.
            #
            # Settlement must be evaluated with the queue drained. A queued node
            # is never "dead", so asking `is X dead?` while X is still queued is
            # circular: two unready siblings would each keep the other alive and
            # report a deadlock that does not exist.
            survivors = list(pending)
            pending.clear()
            stuck = [
                nid for nid in survivors
                if any(not rdy.settled(i) for i in in_flow.get(nid, []))
            ]
            if stuck:
                pending.extend(survivors)
                rep.deadlocked = True
            break
        nid = pending.pop(pick)
        node = nodes[nid]
        rep.steps += 1
        rep.trace.append(nid)
        ran.add(nid)
        forced.discard(nid)

        # `attempts` is owned by the runtime, not by node output. 48 edge guards
        # across the registry read it (`verify_failed and attempts < 3`) and
        # nothing produced it: `edge_true` swallowed the NameError and returned
        # False, so every bounded retry loop silently failed closed unless a
        # fixture happened to supply the value. Publish the visit count — 1 on
        # the first execution — before the node runs, so guards evaluated after
        # it see the attempt that just happened.
        visits[nid] += 1
        bb["attempts"] = visits[nid]

        if node.get("kind") == "human":
            out = _run_gate(node, bb, runner, auto_approve, rep)
        else:
            out = runner.run(node, bb)
        bb.update(out)

        errored = bool(out.get("error"))
        if errored and attempts[nid] < node.get("retries", {}).get("max", 0):
            attempts[nid] += 1
            rep.retries_used += 1
            pending.insert(0, nid)  # retry before draining the rest of the frontier
            continue

        blocked = errored or (nid, False) in rep.approvals
        fired: list[int] = []
        for i in out_edges[nid]:
            e = doc["edges"][i]
            kind = e.get("kind", "flow")
            resolved.add(i)
            if kind == "flow" and blocked:
                continue
            if kind == "error" and not errored:
                continue
            if edge_true(e.get("when"), bb):
                fired.append(i)
        if node.get("kind") == "router" and fired:
            fired = fired[:1]
        for i in fired:
            taken.add(i)
            edge = doc["edges"][i]
            tgt = edge["to"]
            if edge.get("kind", "flow") != "flow":
                forced.add(tgt)
            if tgt not in pending:
                pending.append(tgt)

    for v in doc.get("verification", []):
        if "command" in v:
            if run_commands:
                _run_command(v["command"], root, rep)
            else:
                rep.skipped_commands += 1
            continue
        if "assert" not in v:
            continue  # describe-only: prose, graded as unverified by evalcmd
        try:
            ok = bool(safe_eval(v["assert"], bb))
        except Exception as ex:
            ok, ex_note = False, f" ({type(ex).__name__}: {ex})"
        else:
            ex_note = ""
        if not ok:
            rep.assert_failures.append(v["assert"] + ex_note)
    return rep


def _run_gate(node: dict, bb: dict, runner, auto_approve: bool, rep: RunReport) -> dict:
    """Execute a `kind: human` approval gate and record its outcome."""
    approve = getattr(runner, "approve", None)
    if approve is not None:
        out = approve(node, bb, auto_approve=auto_approve)
    else:
        out = runner.run(node, bb)
    if auto_approve:
        rep.auto_approved = True
    merged = {**bb, **out}
    contract = node["approval"]["contract"]
    try:
        ok = bool(safe_eval(contract, merged))
    except Exception:
        ok = False
    rep.approvals.append((node["id"], ok))
    return out
