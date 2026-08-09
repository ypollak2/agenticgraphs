"""M1 eval harness: execute AGR graphs against a runner and verify contracts.

The interpreter is real (routers, joins, bounded loops, verification asserts).
Runners are pluggable: MockRunner replays golden fixtures (measures graph/contract
mechanics), LLMRunner calls any OpenAI-compatible endpoint (measures model quality).
Every profile records which runner produced it — mock results are marked provisional.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import urllib.request
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

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


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
#: Models routinely emit Python literals inside otherwise-valid JSON. Normalising
#: them is tolerance for a known quirk, not papering over a wrong answer — the
#: keys and values are exactly what the model meant.
_PY_LITERAL = re.compile(r"(?<![\w\"])(True|False|None)(?![\w\"])")
_PY_MAP = {"True": "true", "False": "false", "None": "null"}


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a model reply, tolerantly.

    The original was one line — `text[text.index("{"):text.rindex("}")+1]` — and a
    multi-model sweep showed why that matters: a large share of apparent *model*
    failures were markdown fences, trailing commas, or prose wrapped around
    otherwise-correct JSON. Counting harness brittleness as a model failure would
    misattribute exactly the thing the sweep exists to measure.

    Raises ValueError when there is genuinely no object to find, so a real
    failure is still a failure.
    """
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in model reply: {text[:120]!r}")
    blob = text[start:end + 1]
    repaired = _PY_LITERAL.sub(lambda m: _PY_MAP[m.group(1)], _TRAILING_COMMA.sub(r"\1", blob))
    for candidate in (blob, _TRAILING_COMMA.sub(r"\1", blob), repaired):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    # Last resort: the largest balanced prefix, for a reply truncated mid-object.
    depth = 0
    for i, ch in enumerate(blob):
        depth += (ch == "{") - (ch == "}")
        if depth == 0 and i:
            try:
                return json.loads(blob[: i + 1])
            except json.JSONDecodeError:
                break
    raise ValueError(f"unparseable JSON in model reply: {blob[:120]!r}")


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
    # v1.2 — execution history. A frame is what ONE node execution wrote, not a
    # copy of the board: cheap enough to keep for every step, and the substrate
    # phase-scoped verification, fan-out and reflexion memory all read from.
    frames: list[dict] = field(default_factory=list)
    lessons: list[dict] = field(default_factory=list)
    budget_exhausted: str = ""
    journal: list[dict] = field(default_factory=list)
    resumed_nodes: list[str] = field(default_factory=list)
    state_violations: list[str] = field(default_factory=list)
    truncations: list[str] = field(default_factory=list)
    searches: list[dict] = field(default_factory=list)

    def frames_for(self, node_id: str) -> list[dict]:
        return [f for f in self.frames if f["node"] == node_id]

    def phase_frame(self, phase: str) -> dict:
        """The blackboard state a phase produced, as its child graph would see it.

        Every write made inside the phase, merged in execution order. Not just
        the last one: run standalone, a child graph ends with a blackboard that
        *accumulated* across its nodes, and its asserts were written against
        that. `postmortem-writer` writes `output` in `produce` and then runs
        `review` — taking only the final write would lose the very key the
        child's contract asserts on.
        """
        merged: dict = {}
        for f in self.frames:
            if f["node"] == phase or f["node"].startswith(phase + "."):
                merged.update(f["out"])
        return merged

    @property
    def rejected_approvals(self) -> list[str]:
        return [nid for nid, ok in self.approvals if not ok]

    @property
    def passed(self) -> bool:
        return (not self.assert_failures and not self.command_failures
                and not self.state_violations and not self.budget_exhausted
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

    def _assembly_hint(self, declared: list[str]) -> str:
        """Tell a node that assembles `output` where its contents come from.

        v1.3 declared the asserted sub-keys on the terminal node and re-recorded;
        0 of 12 runs passed. `output` is assembled from facts *upstream* nodes
        established, so "return these keys" asks the terminal to invent values it
        never computed. v1.4 declares each fact on the node that produces it and
        tells the assembler to read them off the blackboard it can already see.
        """
        if "output" not in declared or not self.asserted:
            return ""
        return (
            f"The `output` object must contain: {json.dumps(sorted(self.asserted))}. "
            "Take each value from the blackboard above — do not invent them. "
        )

    def bind(self, doc: dict) -> None:
        """Give the runner the graph's contract before execution starts.

        Without this the prompt asked for "your output keys" without ever saying
        which — so a real model returned plausible-looking JSON with entirely
        different key names and every contract assert failed on AttributeError.
        v1.1 added declared `outputs` per node and the live runner never used them.
        """
        from .validate import asserted_keys  # local: avoids an import cycle

        self.contract = doc.get("termination", {}).get("contract", "")
        self.checks = [v["assert"] for v in doc.get("verification") or [] if "assert" in v]
        self.asserted: set[str] = set()
        for check in self.checks:
            self.asserted |= asserted_keys(check)

    def run(self, node: dict, bb: dict) -> dict:
        declared = node.get("outputs") or []
        wants = (
            f"You MUST return exactly these keys: {json.dumps(declared)}. "
            if declared else
            "Return the keys this step is responsible for. "
        )
        contract = getattr(self, "contract", "")
        checks = getattr(self, "checks", [])
        prompt = (
            f"You are node '{node['id']}' (speciality: {node['speciality']}) in a workflow. "
            f"Abilities: {', '.join(node.get('abilities', []))}.\n"
            f"Blackboard so far: {json.dumps(bb, default=str)}\n"
            + (f"The workflow's exit contract is: {contract}\n" if contract else "")
            + (f"Downstream assertions that must hold: {json.dumps(checks)}\n" if checks else "")
            + wants
            + self._assembly_hint(declared)
            + "Reply with ONLY a JSON object. No prose, no markdown fence."
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
        return extract_json(text)

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


class ReplayRunner:
    """Replays *recorded real-model* outputs from evals/<graph>/live/<case>.json.

    The depth grading shipped in v1.1 could report `assert-live`, but nothing
    ever produced it: a live run needs a network call, so CI never made one and
    every graph stayed at `assert-fixture`. A recording is a real model's output,
    captured once and checked in, so the assert is graded against what a model
    actually said rather than what a fixture author wished it would say.

    Each recording stamps the model and date it came from; the scoreboard shows
    the age, because a recording is evidence with a shelf life.
    """

    def __init__(self, recording: dict):
        self.model = recording.get("model", "unknown")
        self.recorded = recording.get("recorded", "unknown")
        self.node_outputs = recording["node_outputs"]
        self.visits: dict = defaultdict(int)
        self.name = f"llm-replay:{self.model}"

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def run(self, node: dict, bb: dict) -> dict:
        out = self.node_outputs.get(node["id"], {})
        if isinstance(out, list):
            out = out[min(self.visits[node["id"]], len(out) - 1)]
        self.visits[node["id"]] += 1
        return deepcopy(out)

    def approve(self, node: dict, bb: dict, auto_approve: bool = False) -> dict:
        """A recording cannot contain a human signature — refuse like LLMRunner."""
        if not auto_approve:
            raise HumanGateRequired(
                f"node '{node['id']}' is a human approval gate; a replayed model "
                "recording is not a sign-off"
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


#: Rough per-node cost used only to make `budget.usd_max` enforceable without a
#: billing integration. Deliberately crude and deliberately NOT presented as a
#: price: it exists so a cap can halt a run, which beats a cap that is recorded
#: and ignored — the pattern v1.3 exists to stop repeating.
_EST_USD_PER_NODE = 0.002


def run_graph(doc: dict, runner, root=None, auto_approve: bool = False,
              run_commands: bool = False, resume_from=None) -> RunReport:
    """Execute an AGR graph against a runner.

    v1.1 adds: subgraph expansion, join semantics, error/compensate edge kinds,
    per-node retries, and human approval gates. With every node defaulting to
    `join: any` and no v1.1 fields present, scheduling is byte-identical to v1 —
    locked by tests/fixtures/v1_trace_lock.json.
    """
    from .subgraphs import entry_nodes, expand, has_subgraphs  # local: avoids an import cycle

    rep = RunReport()
    if hasattr(runner, "bind"):
        runner.bind(doc)
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
    budget = doc.get("budget") or {}
    # D3: resume is replay. v1.2 already journals every node execution, so a
    # killed run is resumed by replaying its frames and skipping what completed —
    # no new state model, no storage engine.
    completed: dict[str, dict] = {}
    if resume_from:
        for line in Path(resume_from).read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                completed[entry["node"]] = entry["out"]
    rdy = _Readiness(doc, nodes, in_flow, resolved, taken, ran, pending, forced)

    while pending:
        if rep.steps >= cap:
            rep.hit_step_cap = True
            break
        # Budgets are checked *before* the node runs, not after it is recorded:
        # a cap that lets the step it forbids execute first is not a cap.
        if budget.get("steps_max") and rep.steps >= budget["steps_max"]:
            rep.budget_exhausted = (
                f"steps_max={budget['steps_max']} reached; halted before step {rep.steps + 1}"
            )
            break
        if budget.get("usd_max") and (rep.steps + 1) * _EST_USD_PER_NODE > budget["usd_max"]:
            rep.budget_exhausted = (
                f"usd_max=${budget['usd_max']:.4f} would be exceeded by step {rep.steps + 1} "
                f"(estimated ${(rep.steps + 1) * _EST_USD_PER_NODE:.4f})"
            )
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

        _aggregate(node, bb)
        if nid in completed and visits[nid] == 1:
            out = completed.pop(nid)
            rep.resumed_nodes.append(nid)
            rep.frames.append({"node": nid, "visit": 1, "out": out, "resumed": True})
            bb.update(out)
            _fire(nid, node, out, doc, out_edges, resolved, taken, forced, pending, bb, rep)
            continue
        if node.get("kind") == "human":
            out = _run_gate(node, bb, runner, auto_approve, rep)
        elif node.get("fan_out"):
            out = _fan_out(node, bb, runner, rep, visits[nid])
        elif node.get("kind") == "search":
            out = _search(node, bb, runner, rep, visits[nid])
        else:
            out = runner.run(node, bb)
            rep.frames.append({"node": nid, "visit": visits[nid], "out": out})
        bb.update(out)

        errored = bool(out.get("error"))
        if errored and attempts[nid] < node.get("retries", {}).get("max", 0):
            attempts[nid] += 1
            rep.retries_used += 1
            pending.insert(0, nid)  # retry before draining the rest of the frontier
            continue

        _fire(nid, node, out, doc, out_edges, resolved, taken, forced, pending, bb, rep)

    if (doc.get("durability") or {}).get("checkpoint") == "every_node":
        rep.journal = [{"node": f["node"], "out": f["out"]}
                       for f in rep.frames if not f.get("resumed")]

    _check_state(doc, bb, root, rep)
    _persist_memory(doc, bb, root, rep)

    for v in doc.get("verification", []):
        if "command" in v:
            if run_commands:
                _run_command(v["command"], root, rep)
            else:
                rep.skipped_commands += 1
            continue
        if "assert" not in v:
            continue  # describe-only: prose, graded as unverified by evalcmd
        # A phase-tagged assert came from a subgraph child and only ever held at
        # the instant that phase's terminal ran. Evaluating it against the final
        # blackboard — which a later phase has since overwritten — is why v1.1
        # dropped child verification entirely.
        scope = {**bb, **rep.phase_frame(v["phase"])} if v.get("phase") else bb
        try:
            ok = bool(safe_eval(v["assert"], scope))
        except Exception as ex:
            ok, ex_note = False, f" ({type(ex).__name__}: {ex})"
        else:
            ex_note = ""
        if not ok:
            label = f"[{v['phase']}] " if v.get("phase") else ""
            rep.assert_failures.append(label + v["assert"] + ex_note)
    return rep


_AGG = {
    "union": lambda vs: [x for v in vs for x in (v if isinstance(v, list) else [v])],
    "median": lambda vs: sorted(vs)[len(vs) // 2] if vs else None,
    "best": lambda vs: max(vs) if vs else None,
}


def _majority(values: list):
    """Most common value, or None on a tie — a tie is a real signal, not noise."""
    counts: dict = defaultdict(int)
    for v in values:
        counts[json.dumps(v, sort_keys=True, default=str)] += 1
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return json.loads(ranked[0][0])


_AGG["majority"] = _majority


def _aggregate(node: dict, bb: dict) -> None:
    """Reduce a fanned-out list on the blackboard before the node runs.

    Deliberately a node property rather than a new node kind: it reuses the join
    machinery v1.1 already ships instead of inventing a parallel concept.
    """
    spec = node.get("aggregate")
    if not spec:
        return
    values = bb.get(spec["over"])
    if not isinstance(values, list):
        return
    bb[spec["over"]] = _AGG[spec["op"]](values)


def _fan_out(node: dict, bb: dict, runner, rep: RunReport, visit: int) -> dict:
    """Run a node once per element of `fan_out.over`.

    Each shard produces its own frame, so N shards stay N observations instead of
    collapsing into one blackboard write where the last shard silently wins.
    Declared outputs become *lists* downstream — which is why fan_out is opt-in
    rather than inferred from `parallel_group`.
    """
    spec = node["fan_out"]
    items = bb.get(spec["over"])
    if not isinstance(items, list):
        items = []
    cap = spec.get("max", 40)
    if len(items) > cap:
        # Never silent. A truncated fan-out that reports full coverage is exactly
        # the kind of quiet lie this registry exists to refuse.
        rep.truncations.append(
            f"{node['id']}: fanned out over {cap} of {len(items)} '{spec['over']}' "
            f"items (fan_out.max={cap}); {len(items) - cap} not processed"
        )
    shards, results = items[:cap], []
    for i, item in enumerate(shards):
        out = runner.run(node, {**bb, "shard": item, "shard_index": i, "shard_count": len(shards)})
        rep.frames.append({"node": node["id"], "visit": visit, "shard": i, "out": out})
        results.append(out)
    errs = [r for r in results if r.get("error")]
    on_partial = spec.get("on_partial", "continue")
    keys = set(node.get("outputs") or []) | {k for r in results for k in r}
    merged: dict = {k: [r.get(k) for r in results] for k in keys}
    merged["shards_processed"] = len(results)
    merged["shards_failed"] = len(errs)
    if errs and on_partial == "fail":
        merged["error"] = f"{len(errs)} of {len(results)} shards failed"
    return merged


def _search(node: dict, bb: dict, runner, rep: RunReport, visit: int) -> dict:
    """Bounded beam search over candidate outputs.

    This is beam search, not MCTS — no rollout policy and no learned value
    function, because both need a real environment and faking one would produce
    exactly the fixture-deep evidence v1.2 exists to escape. Deterministic,
    inspectable, and bounded by branch x depth.
    """
    spec = node["search"]
    branch, depth = spec.get("branch", 3), spec.get("depth", 2)
    objective = spec.get("objective", "max")
    beam = 1
    if str(spec.get("prune", "")).startswith("beam("):
        beam = int(str(spec["prune"])[5:-1])
    better = (lambda a, b: a < b) if objective == "min" else (lambda a, b: a > b)

    frontier: list[tuple] = [(None, None)]  # (score, candidate)
    log: list[dict] = []
    for d in range(depth):
        scored: list[tuple] = []
        for _, parent in frontier:
            for b in range(branch):
                ctx = {**bb, **(parent or {}), "branch_index": b, "search_depth": d}
                out = runner.run(node, ctx)
                rep.frames.append({"node": node["id"], "visit": visit, "depth": d,
                                   "branch": b, "out": out})
                try:
                    score = safe_eval(spec["score"], {**ctx, **out})
                except Exception:
                    continue  # unscoreable candidate is not a candidate
                # A score that cannot be ordered is no more usable than one that
                # cannot be computed. A real model returned a string here and the
                # sort below took the whole run down with a TypeError instead of
                # dropping one candidate.
                if not isinstance(score, (int, float)) or isinstance(score, bool):
                    continue
                scored.append((score, out))
        if not scored:
            break
        scored.sort(key=lambda sc: sc[0], reverse=(objective == "max"))
        frontier = scored[:beam]
        log.append({"depth": d, "evaluated": len(scored), "best": frontier[0][0]})
    rep.searches.append({"node": node["id"], "rounds": log,
                         "improved": len(log) > 1 and better(log[-1]["best"], log[0]["best"])})
    if not frontier or frontier[0][0] is None:
        return {}
    best_score, best_out = frontier[0]
    return {**best_out, "search_score": best_score, "search_rounds": len(log)}


def _check_state(doc: dict, bb: dict, root, rep: RunReport) -> None:
    """Validate the final blackboard against `state.schema`, if one is declared.

    v1.1 accepted `state.schema` as a string and never read it, deferred to v1.2
    "once it has a consumer". `memory` is that consumer: a graph that persists
    lessons across runs needs its state shape pinned, or the file it accumulates
    becomes untyped sludge. Deferring twice for the same reason is how a spec
    accumulates decoration, so it is enforced here.
    """
    rel = (doc.get("state") or {}).get("schema")
    if not rel or root is None:
        return
    path = Path(root) / rel
    if not path.exists():
        rep.state_violations.append(f"state.schema '{rel}' does not resolve to {path}")
        return
    try:
        import jsonschema

        jsonschema.Draft202012Validator(json.loads(path.read_text())).validate(bb)
    except ImportError:  # pragma: no cover — jsonschema is a hard dependency
        return
    except Exception as ex:
        rep.state_violations.append(f"state does not satisfy {rel}: {ex.args[0] if ex.args else ex}")


def _persist_memory(doc: dict, bb: dict, root, rep: RunReport) -> None:
    """Collect `lessons` and, for `scope: graph`, append them to memory.jsonl.

    A reflexion graph that cannot carry a lesson past the end of one run is a
    retry loop with extra vocabulary. `scope: run` keeps them on the report;
    `scope: graph` persists so the next run reads what the last one learned.
    """
    mem = doc.get("memory")
    if not mem:
        return
    lessons = bb.get("lessons")
    if isinstance(lessons, dict):
        lessons = [lessons]
    if not isinstance(lessons, list):
        return
    rep.lessons = [x for x in lessons if x]
    if mem.get("scope") != "graph" or root is None or not rep.lessons:
        return
    target = Path(root) / "graphs" / doc["category"] / doc["name"] / "memory.jsonl"
    if target.parent.is_dir():
        with target.open("a") as fh:
            for lesson in rep.lessons:
                fh.write(json.dumps({"graph": doc["name"], "lesson": lesson}) + "\n")


def _fire(nid, node, out, doc, out_edges, resolved, taken, forced, pending, bb, rep) -> None:
    """Resolve this node's outgoing edges and enqueue whatever they reach.

    Extracted so a resumed node — whose output is replayed from a journal rather
    than produced by a runner — takes exactly the same routing path as a fresh
    one. Two copies of this logic would let resume diverge from a live run in
    ways the trace-equality test is specifically there to catch.
    """
    errored = bool(out.get("error"))
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
