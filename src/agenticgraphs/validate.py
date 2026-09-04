"""Schema + structural validation for AGR graphs.

Structural lint encodes known multi-agent failure modes (MAST taxonomy):
unreachable nodes, dangling edges, missing verification, unbounded loops,
and unresolvable specialities/abilities.

v1.1 adds lints for the new surface: subgraph refs that resolve, declared I/O
contracts that are actually satisfiable, approval contracts and verification
asserts that parse, and a guard against using v1.1 features under an
`agr/v1` apiVersion.
"""
from __future__ import annotations

import ast
import shlex
from pathlib import Path

import jsonschema

from . import safeexpr
from .registry import ROOT, SPEC_VERSION, iter_yaml, load, load_schema
from .shapes import ShapeError
from .shapes import names as _out_names
from .shapes import parse as _parse_shape
from .subgraphs import MAX_DEPTH, entry_nodes

#: Node/edge/graph keys introduced in AGR v1.1.
_V11_NODE_KEYS = {"ref", "join", "inputs", "outputs", "on_error", "retries", "approval"}
#: Node keys introduced in AGR v1.2.
_V12_NODE_KEYS = {"fan_out", "aggregate", "search"}


#: Names that appear in an assert but are never blackboard keys.
_ASSERT_LITERALS = {
    "trivial", "low", "simple", "medium", "moderate", "high", "complex", "critical",
    "true", "false", "null", "len", "all", "any", "sum", "min", "max", "abs", "round",
    "output",
}


def asserted_keys(expr: str) -> set[str]:
    """Blackboard keys a verification assert actually reads.

    `output.<attr>` accesses plus free bare names, minus comprehension-bound
    variables, level literals and builtins. AST rather than regex on purpose: a
    regex counted `f`, `v` and `for` as blackboard keys, which is exactly the
    kind of near-miss that makes a wrong number look like a finding.

    Returns an empty set for anything unparseable — `lint: verification assert is
    not a parseable expression` already reports that separately.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.comprehension):
            for target in ast.walk(node.target):
                if isinstance(target, ast.Name):
                    bound.add(target.id)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "output"):
            keys.add(node.attr)
        elif isinstance(node, ast.Name) and node.id not in _ASSERT_LITERALS and node.id not in bound:
            keys.add(node.id)
    return keys


#: Names the runtime owns, so a guard may read them without any node declaring them.
_RUNTIME_KEYS = frozenset({"attempts", "shards_failed", "shards_processed"})


def unconnected_keys(doc: dict) -> set[str]:
    """Keys the contract asserts on that nothing in the graph is declared to produce.

    THE v1.4 gap. A graph's node I/O contracts and its verification contract were
    two separate vocabularies with nothing checking they referred to the same
    things: 123 of 183 asserted keys across the registry were produced by no
    declared output. That is how four contracts stayed structurally valid, passed
    the whole suite, and were satisfiable by no model.
    """
    produced = {o for n in doc.get("nodes", []) for o in _out_names(n)}
    produced |= set((doc.get("state") or {}).get("inputs") or [])
    # The runtime publishes these; `_lint_runtime_keys` refuses a node that also
    # declares one. Two lints disagreeing about who owns `attempts` would make one
    # of them unsatisfiable — a contract reading the real retry counter would be
    # reported as asserting on a key nothing produces.
    produced |= _RUNTIME_KEYS
    # No early return for graphs that declare nothing. An earlier draft excused
    # them — "a node that declares nothing makes no promise to break" — and that
    # escape hatch swallowed exactly the case it most needed to catch:
    # `code-review-pipeline` asserted on `output.verdict` while declaring no
    # outputs at all, so it read as fully connected and was promoted to v1.4.
    # Declaring nothing is not a defence; it is the maximal form of the gap.
    needed: set[str] = set()
    for v in doc.get("verification") or []:
        if "assert" in v:
            needed |= asserted_keys(v["assert"])
    return needed - produced


def _lint_expressions(doc: dict) -> list[str]:
    """Refuse any `when` / `assert` / approval contract the evaluator would refuse.

    The runtime allowlist (`safeexpr`) is the security boundary; this is the same
    boundary moved forward to `agr validate`, so CI and a reviewer see the
    rejection before an interpreter does.
    """
    errors: list[str] = []
    for e in doc.get("edges", []):
        for reason in safeexpr.check(e.get("when") or ""):
            errors.append(f"unsafe expression on edge {e['from']}->{e['to']}: {reason}")
    for v in doc.get("verification", []):
        for reason in safeexpr.check(v.get("assert") or ""):
            errors.append(f"unsafe verification assert: {reason}")
    for n in doc.get("nodes", []):
        contract = (n.get("approval") or {}).get("contract", "")
        for reason in safeexpr.check(contract):
            errors.append(f"unsafe approval contract on '{n['id']}': {reason}")
        for reason in safeexpr.check((n.get("search") or {}).get("score", "")):
            errors.append(f"unsafe search score on '{n['id']}': {reason}")
    return errors


def _bare_truthy_key(expr: str) -> str | None:
    """The key an assert reads if it is *only* a truthiness check, else None.

    Matches `output.x`, `output.x == true`, `x`, `x == True` — the shapes that
    assert nothing beyond "the graph said so".
    """
    try:
        tree = ast.parse(expr, mode="eval").body
    except SyntaxError:
        return None
    if isinstance(tree, ast.Compare) and len(tree.ops) == 1 and isinstance(tree.ops[0], ast.Eq):
        rhs = tree.comparators[0]
        lit = getattr(rhs, "value", getattr(rhs, "id", None))
        if lit is True or (isinstance(lit, str) and lit.lower() == "true"):
            tree = tree.left
        else:
            return None
    if isinstance(tree, ast.Attribute) and isinstance(tree.value, ast.Name) and tree.value.id == "output":
        return tree.attr
    if isinstance(tree, ast.Name):
        return tree.id
    return None


def _lint_self_graded(doc: dict) -> list[str]:
    """A contract a verifier node grades itself on is not verification.

    `verify` declares `outputs: [matches_ownership_map]`; the contract asserts
    `output.matches_ownership_map`. The model writes the flag and the flag is the
    pass criterion, so the check holds whenever the model claims it does — which
    is every time. Six graphs in the registry were built this way, and 31 of 117
    asserts are a bare truthy read of *something*.

    The fix a graph author has is to assert on a fact an upstream node produced
    and this node had to reconcile, or to add a `verification[].command` that
    checks the claim outside the model. Both are real work; that is the point.
    """
    # Any node a MODEL drives, not only `kind: verifier`. The rule was written for
    # the verifier case and missed eight contracts where the flag is written by an
    # ordinary agent — `post` deciding `three_way_matched`, `disclose` deciding
    # `advisory_published`. The node's kind never mattered; who writes the flag does.
    #
    # `kind: human` is the exemption, and the only one. A signature IS evidence:
    # `output.signed_off == true` is a claim by a person the graph refused to make
    # on their behalf (see `LLMRunner.approve`), which is the opposite of
    # self-grading. Seven contracts rest on that and are correct.
    verifier_outputs: dict[str, str] = {}
    for n in doc.get("nodes", []):
        if n.get("kind") == "human":
            continue
        for o in _out_names(n):
            verifier_outputs.setdefault(o, n["id"])
    msgs: list[str] = []
    for v in doc.get("verification") or []:
        key = _bare_truthy_key(v.get("assert") or "")
        if key and key in verifier_outputs:
            msgs.append(
                f"self-graded contract: assert '{v['assert']}' reads a key that node "
                f"'{verifier_outputs[key]}' produces itself — the model "
                f"writes the flag it is scored on. Assert on a fact an upstream node "
                f"produced, or add a verification[].command."
            )
    # Armed at v1.8, the same way `_lint_provenance` armed at v1.6: the rule
    # ships with the spec version whose graphs are expected to satisfy it, so a
    # v1.7 registry is not retroactively failed by a rule written after it. The
    # graphs it currently finds are written to `reports/self-graded.json` by
    # scripts/gen_self_graded.py (regenerated in `make regen`, diffed in CI) and
    # migrated one at a time, each with a real check replacing the flag.
    if doc.get("apiVersion", "") < "agr/v1.8":
        return []
    return msgs


def _lint_criteria(doc: dict) -> list[str]:
    """A verifier without a rubric is a role label, not a verifier.

    Armed at v1.8. Before it, a node carried only its position in a topology, so
    two graphs in unrelated domains could be — and 36 of 83 were — the same nodes
    under different names. `criteria` is where the domain knowledge lives, and
    requiring it on the node that makes the judgement is what stops a graph from
    being a shape the reader could have typed themselves.
    """
    if doc.get("apiVersion", "") < "agr/v1.8":
        return []
    return [
        f"node '{n['id']}' is kind: verifier but declares no `criteria` — state what it "
        f"must judge, in this domain's terms, not which flag to set"
        for n in doc.get("nodes", [])
        if n.get("kind") == "verifier" and not (n.get("criteria") or "").strip()
    ]


#: Function words. A command line does not contain them as bare tokens.
_PROSE_WORDS = frozenset({
    "must", "should", "shall", "the", "a", "an", "is", "are", "be", "was", "were",
    "that", "this", "which", "and", "or", "not", "with", "from", "when", "if",
})


def _lint_commands(doc: dict) -> list[str]:
    """A `verification[].command` must be runnable, not a description of one.

    `verifier-swarm` shipped `command: "user-supplied verify command must exit 0"`
    — prose in the field whose entire purpose is that the exit code, not a claim
    about it, is the fact. Under `--run-commands` that would have tried to execute
    the program `user-supplied` and recorded a command_failure that looked like a
    failing check rather than a malformed graph.

    The heuristic is deliberately narrow: several bare words, none of which looks
    like a flag, a path, or a placeholder, is a sentence. Anything a real command
    line contains — `-q`, `tests/`, `{suite}`, `./x` — passes.
    """
    errors: list[str] = []
    for v in doc.get("verification") or []:
        cmd = v.get("command")
        if not cmd:
            continue
        try:
            argv = shlex.split(cmd)
        except ValueError as ex:
            errors.append(f"verification command is not parseable: {cmd!r} ({ex})")
            continue
        if not argv:
            errors.append("verification command is empty")
            continue
        looks_like_argv = any(
            t.startswith(("-", "/", "./", "{")) or "/" in t or "." in t or "=" in t
            for t in argv
        )
        # Counting tokens was the first attempt and it called `alembic upgrade head`
        # prose. What actually separates a sentence from a command line is function
        # words: no CLI has a bare `must` or `the` in it. A command that legitimately
        # passes one as an argument will also carry a flag, path or placeholder, and
        # `looks_like_argv` clears it.
        reads_as_prose = bool({t.lower() for t in argv} & _PROSE_WORDS)
        if reads_as_prose and not looks_like_argv:
            errors.append(
                f"verification command reads as prose, not a command line: {cmd!r} — "
                f"name the program to run, or use a {{placeholder}} the caller fills"
            )
    return errors


#: Effects no revert undoes. A filing is received the moment it is submitted; a
#: registration is public; a cut release is downloadable; a resubmitted billing
#: code has been claimed against. `edit_files` is deliberately ABSENT: a working
#: tree is reversible by `git revert`, and marking it as a saga step would dress a
#: reversible action in the vocabulary reserved for one-way ones — which is how a
#: compensator count grows without any compensation being possible.
_IRREVERSIBLE_ABILITIES = frozenset({
    "file_record", "cut_release", "shadow_write", "backfill",
})


def _lint_irreversible(doc: dict) -> list[str]:
    """A one-way effect needs a compensating path, or the graph cannot be unwound.

    Armed at v1.8. The v1.3 saga lint already required this of graphs whose
    declared pattern is `saga`; the property has nothing to do with what a graph
    calls itself. `regulatory-filing-lifecycle` files with a regulator and had no
    way back.
    """
    if doc.get("apiVersion", "") < "agr/v1.8":
        return []
    compensated = {e["from"] for e in doc.get("edges", []) if e.get("kind") == "compensate"}
    return [
        f"node '{n['id']}' performs a one-way effect ({sorted(hit)}) with no compensate "
        f"edge — name the action that undoes it on the record, or drop the ability"
        for n in doc.get("nodes", [])
        if (hit := _IRREVERSIBLE_ABILITIES & set(n.get("abilities") or []))
        and n["id"] not in compensated
    ]


def _lint_motif(doc: dict, root: Path = ROOT) -> list[str]:
    """A graph's declared motif must be visible in its topology.

    Every graph declares a `pattern` in its `usecase.yaml`, and nothing has ever
    checked it. Ten graphs called themselves `parallel-swarm` while being a linear
    three-node chain — `verifier-swarm`, the one the README uses to explain what a
    swarm is, among them. A motif nothing verifies is the same defect as a contract
    nothing verifies: a claim living in the artifact, which is what this registry
    exists to stop.

    Each rule names the structure the motif is *about*, not a proxy for it. A
    debate is defined by two positions reaching one judge, so it is in-degree, not
    fan-out; a router is defined by mutually exclusive conditional edges, so a
    `kind: router` node is sufficient but not necessary.
    """
    if doc.get("apiVersion", "") < "agr/v1.8":
        return []
    pattern = doc.get("__pattern__")
    if not pattern:
        return []
    nodes, edges = doc.get("nodes", []), doc.get("edges", [])
    ids = [n["id"] for n in nodes]
    out_deg: dict[str, int] = {}
    in_deg: dict[str, int] = {}
    cond_out: dict[str, int] = {}
    for e in edges:
        if e.get("kind") == "compensate":
            continue
        out_deg[e["from"]] = out_deg.get(e["from"], 0) + 1
        in_deg[e["to"]] = in_deg.get(e["to"], 0) + 1
        if e.get("when"):
            cond_out[e["from"]] = cond_out.get(e["from"], 0) + 1
    groups: dict[str, int] = {}
    for n in nodes:
        if g := n.get("parallel_group"):
            groups[g] = groups.get(g, 0) + 1

    has_fan_out = any(n.get("fan_out") for n in nodes)
    has_group = any(v >= 2 for v in groups.values())
    max_in = max(in_deg.values(), default=0)
    max_out = max(out_deg.values(), default=0)
    routes = any(v >= 2 for v in cond_out.values()) or any(
        n.get("kind") == "router" for n in nodes)
    back_edge = any(
        e.get("when") and e["to"] in ids and e["from"] in ids
        and ids.index(e["to"]) <= ids.index(e["from"])
        for e in edges
    )

    def fail(why: str) -> list[str]:
        return [f"declares motif '{pattern}' but {why}"]

    if pattern == "router" and not routes:
        return fail("no node routes: none is `kind: router` and none has two "
                    "conditional out-edges")
    if pattern in ("parallel-swarm", "map-reduce") and not (has_fan_out or has_group):
        return fail("nothing is declared independent: no node declares `fan_out` and no "
                    "`parallel_group` has two members (a group declares that its members "
                    "may run concurrently; the reference runtime schedules them serially)")
    if pattern in ("debate", "ensemble-quorum") and max_in < 2 and not has_fan_out:
        return fail("only one contribution reaches the adjudicator — there is "
                    "nobody to disagree with")
    if pattern == "tournament" and not has_fan_out and max_in < 3:
        return fail("fewer than three entrants reach the judge")
    if pattern == "loop" and not back_edge:
        return fail("no conditional back-edge")
    if pattern == "reflexion" and not doc.get("memory"):
        return fail("no `memory` block, so nothing carries between attempts")
    if pattern == "human-gate" and not any(n.get("kind") == "human" for n in nodes):
        return fail("no `kind: human` node")
    if pattern == "saga" and not any(e.get("kind") == "compensate" for e in edges):
        return fail("no compensate edge, so it cannot unwind")
    if pattern == "tree-search" and not any(n.get("search") for n in nodes):
        return fail("no node declares a `search` block")
    if pattern == "pipeline" and max_out > 1 and not (has_group or routes):
        return fail("it branches without a router or a parallel group, which is "
                    "not a pipeline")
    return []


def _flow_names(expr: str) -> set[str]:
    """Bare names an edge guard or approval contract depends on."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    bound = {t.id for n in ast.walk(tree) if isinstance(n, ast.comprehension)
             for t in ast.walk(n.target) if isinstance(t, ast.Name)}
    return {
        n.id for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id not in _ASSERT_LITERALS
        and n.id not in bound and n.id not in _RUNTIME_KEYS
    }


def _lint_runtime_keys(doc: dict) -> list[str]:
    """A node may not declare a key the runtime owns.

    `attempts` is published by `run_graph` before each node runs, as the visit
    count. A node that also declares it lets a fixture — or a model — pin it to a
    constant, and `verify_failed and attempts < 3` then never terminates:
    `verifier-swarm` ran its retry loop to the step cap the moment the guard
    started working, because the fixture said `attempts: 1` forever.

    Nothing needs to declare it. `output.attempts` resolves through `OutputView`'s
    fall-through to the blackboard, so a contract can read the real counter while
    no node claims to produce it.
    """
    if doc.get("apiVersion", "") < "agr/v1.8":
        return []
    return [
        f"node '{n['id']}' declares '{key}', which the runtime owns — declaring it "
        f"lets a fixture pin the value and a bounded loop never terminate"
        for n in doc.get("nodes", [])
        for key in sorted(set(_out_names(n)) & _RUNTIME_KEYS)
    ]


def _lint_flow_keys(doc: dict) -> list[str]:
    """A guard reading a key nothing produces is a dead edge, and it fails SILENTLY.

    `edge_true` catches any exception and returns False, so a condition naming an
    undeclared key is not an error — it is an edge that is never taken. That is
    the correct behaviour for an unresolvable condition at run time and a
    catastrophe at authoring time: the retry never retries, the compensator never
    compensates, the escalation never escalates, and every golden case still
    passes because the fixture happens to supply the key by hand.

    v1.7 found exactly this for `attempts` — 48 guards read it and nothing
    produced it — and fixed that one name by publishing it from the runtime. The
    same hole was left open for every OTHER guard key: `verify_failed`,
    `revision_requested`, `rejected`, `<node>_failed`. No node in the registry
    declared any of them.

    `unconnected_keys` has applied this rule to verification asserts since v1.4.
    Control flow deserves it more: a broken assert reports a failure, a broken
    guard reports nothing at all.
    """
    if doc.get("apiVersion", "") < "agr/v1.8":
        return []
    produced = {o for n in doc.get("nodes", []) for o in _out_names(n)}
    produced |= set((doc.get("state") or {}).get("inputs") or [])
    errors: list[str] = []
    for e in doc.get("edges", []):
        for name in sorted(_flow_names(e.get("when") or "") - produced):
            errors.append(
                f"edge {e['from']}->{e['to']} is guarded on '{name}', which no node "
                f"declares as an output — the edge can never be taken, silently"
            )
    for n in doc.get("nodes", []):
        contract = (n.get("approval") or {}).get("contract", "")
        for name in sorted(_flow_names(contract) - produced):
            errors.append(
                f"approval on '{n['id']}' depends on '{name}', which no node declares"
            )
    return errors


def _lint_stall(doc: dict) -> list[str]:
    """A bounded retry must have somewhere to go when the bound is reached.

    The registry's decision points share one shape:

        confirm -> mitigate   when: not impact_cleared and attempts < 3
        confirm -> postmortem when: impact_cleared

    Retry while failing with attempts left; advance when it worked. Nothing covers
    still-failing-and-out-of-attempts, so the run stops — not failed, not
    escalated, just stopped, with the contract reporting a missing key from a node
    that was never reached.

    Detected structurally rather than by evaluating conditions: a node with a
    back-edge guarded on `attempts < N` needs a third outgoing edge, one that is
    neither the retry nor the sole success path. What that edge does is the
    author's business; that one exists is not.
    """
    if doc.get("apiVersion", "") < "agr/v1.8":
        return []
    order = {n["id"]: i for i, n in enumerate(doc.get("nodes", []))}
    out: dict[str, list[dict]] = {}
    for e in doc.get("edges", []):
        out.setdefault(e["from"], []).append(e)
    errors: list[str] = []
    for nid, edges in out.items():
        if any(e.get("kind") in ("compensate", "error") for e in edges):
            continue  # a failure path already exists, whatever it is guarded on
        retry = [e for e in edges
                 if "attempts <" in (e.get("when") or "")
                 and order.get(e["to"], 0) <= order.get(nid, 0)]
        forward = [e for e in edges
                   if e not in retry and order.get(e["to"], 0) > order.get(nid, 0)]
        # No forward edge means this node IS a terminal that happens to loop. The
        # run ending there when the bound is reached is the correct outcome, not a
        # stall — counting those turned 11 real findings into 51.
        if not forward:
            continue
        if len(forward) >= 2:
            continue  # a fork with alternatives; whether they are exhaustive is
            # `_lint_flow_keys`' business, not this rule's
        if not forward[0].get("when"):
            continue  # an unconditional way forward always exists
        if retry:
            errors.append(
                f"node '{nid}' retries while `{retry[0]['when']}` and has one way "
                f"forward (`{forward[0]['when']}`) — nothing covers the retry bound "
                f"being reached, so an exhausted loop stalls mid-graph instead of "
                f"escalating"
            )
        else:
            # The same hole without even a retry: the only way on is success, so
            # failure is unrepresentable rather than merely unhandled.
            errors.append(
                f"node '{nid}' has exactly one way forward (`{forward[0]['when']}`) "
                f"and no path for the condition being false — the graph cannot "
                f"express this step failing"
            )
    return errors


def _parses(expr: str) -> bool:
    try:
        ast.parse(expr, mode="eval")
    except SyntaxError:
        return False
    return True


def _lint_v11(doc: dict, root: Path) -> list[str]:
    """Lints for the AGR v1.1 surface. Returns [] for a pure-v1 graph."""
    errors: list[str] = []
    node_ids = {n["id"] for n in doc.get("nodes", [])}
    used: set[str] = set()

    for n in doc.get("nodes", []):
        used |= _V11_NODE_KEYS & n.keys()
        if n.get("kind") == "subgraph":
            used.add("kind: subgraph")
            ref = n.get("ref", "")
            if not (root / "graphs" / ref / "graph.yaml").exists():
                errors.append(f"lint: node '{n['id']}' subgraph ref '{ref}' does not resolve")
            # Child verification does not survive expansion (see subgraphs.expand),
            # so a composite that declares nothing verifies nothing.
            if not doc.get("verification"):
                errors.append(
                    f"lint: node '{n['id']}' embeds subgraph '{ref}' but the graph declares no "
                    "verification — a composite must state what its phases achieved"
                )
        if n.get("kind") == "human":
            contract = (n.get("approval") or {}).get("contract", "")
            if contract and not _parses(contract):
                errors.append(
                    f"lint: node '{n['id']}' approval contract is not a parseable expression: {contract!r}"
                )
        if n.get("on_error") and n["on_error"] not in node_ids:
            errors.append(f"lint: node '{n['id']}' on_error targets unknown node '{n['on_error']}'")

    produced_all = {o for n in doc.get("nodes", []) for o in _out_names(n)}
    supplied_all = set((doc.get("state") or {}).get("inputs") or [])
    # A phase is valid either as an unexpanded `kind: subgraph` node, or — once
    # expanded — as the id prefix its child's nodes now carry. Both forms are
    # validated: `agr validate` sees the authored doc, the harness the expanded one.
    phases = {n["id"] for n in doc.get("nodes", []) if n.get("kind") == "subgraph"}
    phases |= {n["id"].split(".")[0] for n in doc.get("nodes", []) if "." in n["id"]}
    for n in doc.get("nodes", []):
        v12 = _V12_NODE_KEYS & n.keys()
        if v12:
            used |= v12
        fo = n.get("fan_out")
        if fo and fo["over"] not in produced_all | supplied_all:
            errors.append(
                f"lint: node '{n['id']}' fans out over '{fo['over']}' which no node outputs "
                "and state.inputs does not supply — it would fan out over nothing"
            )
        ag = n.get("aggregate")
        if ag and ag["over"] not in produced_all | supplied_all:
            errors.append(
                f"lint: node '{n['id']}' aggregates '{ag['over']}' which nothing produces"
            )
        if n.get("kind") == "search":
            used.add("kind: search")
            if not _parses(n.get("search", {}).get("score", "")):
                errors.append(
                    f"lint: node '{n['id']}' search score is not a parseable expression"
                )
    for v in doc.get("verification") or []:
        if v.get("phase"):
            used.add("verification.phase")
            if v["phase"] not in phases:
                errors.append(
                    f"lint: verification phase '{v['phase']}' is not a kind: subgraph node"
                )
    if doc.get("memory"):
        used.add("memory")

    for e in doc.get("edges", []):
        if e.get("kind", "flow") != "flow":
            used.add("edge kind")
    if (doc.get("state") or {}).get("inputs"):
        used.add("state.inputs")
    if any("describe" in v for v in doc.get("verification") or []):
        used.add("verification.describe")

    # v1.7 — the goal contract. `state.inputs` was declared by 31 graphs and
    # seeded by nothing for five versions; these lints exist so `goal` cannot
    # repeat that, in either direction: declared-but-unsupplied, or
    # consumed-but-undeclared.
    goal = doc.get("goal") or {}
    supplied_keys = set((doc.get("state") or {}).get("inputs") or [])
    # Deliberately NOT added to `used`: that set drives the v1.1 gate, and a
    # goal is not a v1.1 feature. Its own gate is the line below.
    if goal and doc.get("apiVersion") != SPEC_VERSION:
        errors.append(
            f"lint: declares a goal but apiVersion is '{doc.get('apiVersion')}' — "
            f"bump to '{SPEC_VERSION}'"
        )
    if goal.get("required"):
        if "goal" not in supplied_keys:
            errors.append(
                "lint: goal.required is set but state.inputs does not list 'goal' — "
                "the requirement would be enforced against a key nothing supplies"
            )
        if not goal.get("description"):
            errors.append(
                "lint: goal.required is set with no goal.description — a refusal "
                "must be able to say what the caller should bring"
            )
        if doc.get("triggers") and not goal.get("supplied_by_trigger"):
            errors.append(
                "lint: goal.required with triggers but no goal.supplied_by_trigger — "
                "the graph could never fire on its own schedule"
            )
    consumers = [n["id"] for n in doc.get("nodes", []) if "goal" in (n.get("inputs") or [])]
    if consumers and not goal:
        errors.append(
            f"lint: node(s) {sorted(consumers)} declare a 'goal' input but the graph "
            "declares no goal block — the v1.4 disconnect, in a new field"
        )

    v12_used = used & (_V12_NODE_KEYS | {"kind: search", "verification.phase", "memory"})
    if v12_used and doc.get("apiVersion") in ("agr/v1", "agr/v1.1"):
        errors.append(
            f"lint: uses v1.2 features {sorted(v12_used)} but declares apiVersion "
            f"'{doc.get('apiVersion')}' — bump to 'agr/v1.2'"
        )
    if used and doc.get("apiVersion") == "agr/v1":
        errors.append(
            f"lint: uses v1.1 features {sorted(used)} but declares apiVersion 'agr/v1' — "
            "bump to 'agr/v1.1'"
        )

    # Declared I/O contract: an input must be produced by a node that can actually
    # REACH this one, or supplied at graph entry. v1.1 checked set membership —
    # "does this key exist anywhere in the graph" — which passes even when the
    # only producer runs strictly downstream and the value can never arrive.
    # Reachability is only checkable now that v1.5 gave every dependent node an
    # output to be reachable *from*.
    supplied = set((doc.get("state") or {}).get("inputs") or [])
    reachable_out = _upstream_outputs(doc)
    for n in doc.get("nodes", []):
        unmet = set(n.get("inputs") or []) - reachable_out.get(n["id"], set()) - supplied
        if unmet:
            errors.append(
                f"lint: node '{n['id']}' declares inputs {sorted(unmet)} that no node "
                "reaching it outputs and state.inputs does not supply"
            )

    # A saga must be able to undo itself: any node holding an execute-risk
    # ability needs an outgoing compensate edge.
    if doc.get("name", "").endswith("-saga"):
        risks = {load(p)["name"]: load(p).get("risk") for p in iter_yaml("abilities", root)}
        compensating = {e["from"] for e in doc.get("edges", []) if e.get("kind") == "compensate"}
        # The compensators themselves are the undo path — they do not need one.
        compensators = {e["to"] for e in doc.get("edges", []) if e.get("kind") == "compensate"}
        chained = set(compensators)
        for _ in range(len(doc.get("nodes", []))):  # follow compensator -> compensator chains
            chained |= {e["to"] for e in doc.get("edges", []) if e["from"] in chained}
        for n in doc.get("nodes", []):
            if n["id"] in chained:
                continue
            if (any(risks.get(a) == "execute" for a in n.get("abilities") or [])
                    and n["id"] not in compensating):
                    errors.append(
                        f"lint: saga node '{n['id']}' has an execute-risk ability but no "
                        "compensate edge — the step cannot be undone"
                    )
    return errors


def validate_schema(doc: dict, kind: str) -> list[str]:
    v = jsonschema.Draft202012Validator(load_schema(kind))
    return [f"schema: {e.message}" for e in v.iter_errors(doc)]


def lint_ability(doc: dict) -> list[str]:
    """An ability's declared binding must resolve.

    An unbound write/execute ability is allowed but is *narration* until a node
    says so (see `_lint_unbound`).
    """
    from .bindings import BindingError, resolve_binding

    if not doc.get("binding"):
        return []
    try:
        fn = resolve_binding(doc)
    except BindingError as ex:
        return [f"lint: {ex}"]
    if fn is None:
        return [f"lint: {doc['name']}: binding.kind {doc['binding'].get('kind')!r} has no "
                "resolver in this runtime — declare kind: builtin or drop the binding"]
    return []


def _bindable(abilities: dict[str, dict]) -> set[str]:
    from .bindings import BUILTINS, BindingError, resolve_binding

    out = set()
    for name, adoc in abilities.items():
        try:
            fn = resolve_binding(adoc) if adoc.get("binding") else BUILTINS.get(name)
        except BindingError:
            fn = None
        if fn is not None:
            out.add(name)
    return out


def _lint_unbound(doc: dict, abilities: dict[str, dict]) -> list[str]:
    """A write/execute ability with no binding is the model narrating an effect.

    29 of 32 abilities, every irreversible one included, fell back to the plain
    LLM runner: a node declaring `cut_release` cut nothing and its JSON was the
    whole fact (2026-09-04 audit, D2-01; owner decision Q1: lint first, bind
    later). The node may keep the ability, but must say `unbound_ok: <why>` so
    the narration is declared rather than implicit.
    """
    if doc.get("apiVersion", "") < "agr/v1.8":
        return []
    bindable = _bindable(abilities)

    def _world_effect(a: dict) -> bool:
        # `generate`, `reduce_merge`, `write_docs` are `risk: write` but write to
        # the blackboard: producing text IS what a model does, not narration of an
        # effect elsewhere. What needs a binding is an effect outside the run —
        # every execute-risk ability, and a write-risk one that repeats its effect
        # (`edit_files`, `escalate`, `approve`).
        risk = a.get("risk", "read")
        return risk == "execute" or (risk == "write" and a.get("idempotent", True) is False)

    errors = []
    for n in doc.get("nodes", []):
        if n.get("kind") in ("subgraph", "human"):
            continue
        narrated = sorted(a for a in n.get("abilities") or []
                          if a in abilities and _world_effect(abilities[a]) and a not in bindable)
        if narrated and not n.get("unbound_ok"):
            errors.append(
                f"lint: node '{n['id']}' declares {narrated} with no binding — its effect is "
                "the model's account of it. Bind the ability, or declare "
                "`unbound_ok: <why narration is acceptable here>` on the node"
            )
    return errors


def _lint_retry_reissue(doc: dict, abilities: dict[str, dict]) -> list[str]:
    """A retry re-runs the node; with a non-idempotent ability it re-issues the effect.

    39 nodes retried `run_command`/`edit_files` with no concept of idempotency
    anywhere (2026-09-04 audit, D1-02). The ability declares `idempotent: false`;
    the node must then declare `retries.reissue_effects: true` to say it accepts
    a repeated effect, or drop the retry.
    """
    if doc.get("apiVersion", "") < "agr/v1.8":
        return []
    errors = []
    for n in doc.get("nodes", []):
        r = n.get("retries") or {}
        if not r.get("max"):
            continue
        risky = sorted(a for a in n.get("abilities") or []
                       if a in abilities and abilities[a].get("idempotent", True) is False)
        if risky and not r.get("reissue_effects"):
            errors.append(
                f"lint: node '{n['id']}' retries up to {r['max']}x but {risky} is not "
                "idempotent — a retry re-issues the effect. Declare "
                "`retries.reissue_effects: true` to accept that, or remove the retry"
            )
    return errors


def _lint_ref_graph(doc: dict, root: Path) -> list[str]:
    """Walk `kind: subgraph` refs without executing anything.

    `subgraphs.expand` raises on a cycle or on nesting past MAX_DEPTH, but
    `agr validate` never called it, so a composite that referenced itself
    through another graph linted clean and only failed at run time
    (2026-09-04 audit, D4-02). The walk is the static half of that guard.
    """
    errors: list[str] = []
    seen_cycles: set[tuple[str, ...]] = set()

    def walk(d: dict, path: tuple[str, ...]) -> None:
        for n in d.get("nodes", []):
            if n.get("kind") != "subgraph":
                continue
            ref = n.get("ref", "")
            if ref in path:
                cyc = (*path[path.index(ref):], ref)
                if cyc not in seen_cycles:
                    seen_cycles.add(cyc)
                    errors.append(f"lint: subgraph cycle {' -> '.join(cyc)}")
                continue
            if len(path) >= MAX_DEPTH:
                errors.append(
                    f"lint: subgraph nesting exceeds MAX_DEPTH={MAX_DEPTH} at "
                    f"{' -> '.join((*path, ref))}"
                )
                continue
            gp = root / "graphs" / ref / "graph.yaml"
            if not gp.exists():
                continue  # reported by the ref-resolves check
            walk(load(gp), (*path, ref))

    start = f"{doc.get('category', '?')}/{doc.get('name', '?')}"
    walk(doc, (start,))
    return errors


def lint_graph(doc: dict, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    node_ids = [n["id"] for n in doc.get("nodes", [])]
    if len(node_ids) != len(set(node_ids)):
        errors.append("lint: duplicate node ids")

    # dangling edges
    for e in doc.get("edges", []):
        for end in ("from", "to"):
            if e[end] not in node_ids:
                errors.append(f"lint: edge references unknown node '{e[end]}'")

    # reachability from entry nodes: a node is an entry if it has no incoming
    # *unconditional* edge (conditional back-edges do not define forward flow)
    entries = entry_nodes(doc)
    if not entries:
        errors.append("lint: no entry node (cycle with no way in)")
    seen, frontier = set(entries), list(entries)
    while frontier:
        cur = frontier.pop()
        for e in doc.get("edges", []):
            if e["from"] == cur and e["to"] not in seen:
                seen.add(e["to"])
                frontier.append(e["to"])
    unreachable = set(node_ids) - seen
    if unreachable:
        errors.append(f"lint: unreachable nodes {sorted(unreachable)}")

    # A verifier that only the failure path reaches never runs on the happy path,
    # so the graph's proof would fire only when something had already gone wrong.
    # The walk above counts error/compensate edges as reachability on purpose
    # (a rollback handler is a real node); this narrower check is for verifiers
    # (2026-09-04 audit, D1-05). No registry graph relied on it at the time.
    flow_seen, frontier = set(entries), list(entries)
    while frontier:
        cur = frontier.pop()
        for e in doc.get("edges", []):
            if e["from"] == cur and e.get("kind", "flow") == "flow" and e["to"] not in flow_seen:
                flow_seen.add(e["to"])
                frontier.append(e["to"])
    for n in doc.get("nodes", []):
        if n.get("kind") == "verifier" and n["id"] in seen and n["id"] not in flow_seen:
            errors.append(
                f"lint: verifier '{n['id']}' is reachable only through error/compensate "
                "edges — it never runs on the path the contract is about"
            )

    if any(n.get("kind") == "subgraph" for n in doc.get("nodes", [])):
        errors.extend(_lint_ref_graph(doc, root))

    # verification required for graphs with a verifier node
    if any(n.get("kind") == "verifier" for n in doc.get("nodes", [])) and not doc.get("verification"):
        errors.append("lint: graph has verifier node but no verification block")

    # unbounded loop guard: any back-edge must carry a 'when' condition.
    # Compensate edges are reverse paths by construction and are exempt.
    order = {nid: i for i, nid in enumerate(node_ids)}
    for e in doc.get("edges", []):
        if e.get("kind") == "compensate":
            continue
        if order.get(e["to"], 0) <= order.get(e["from"], 0) and not e.get("when"):
            errors.append(f"lint: unconditional back-edge {e['from']}->{e['to']}")

    # verification asserts must be evaluable expressions, not prose
    for v in doc.get("verification", []):
        if "assert" in v and not _parses(v["assert"]):
            errors.append(f"lint: verification assert is not a parseable expression: {v['assert']!r}")

    # Every expression the runtime will evaluate must survive the same allowlist
    # the runtime applies. A graph is a downloaded artifact: catching a hostile
    # expression at the gate is the difference between a rejected contribution
    # and code running on whoever typed `agr eval`.
    errors.extend(_lint_expressions(doc))
    errors.extend(_lint_self_graded(doc))
    errors.extend(_lint_criteria(doc))
    errors.extend(_lint_commands(doc))
    errors.extend(_lint_irreversible(doc))
    errors.extend(_lint_motif(doc, root))
    errors.extend(_lint_flow_keys(doc))
    errors.extend(_lint_stall(doc))
    errors.extend(_lint_runtime_keys(doc))

    # speciality / ability resolution
    specs = {load(p)["name"]: load(p) for p in iter_yaml("specialities", root)}
    ability_docs = {load(p)["name"]: load(p) for p in iter_yaml("abilities", root)}
    abilities = set(ability_docs)
    errors.extend(_lint_unbound(doc, ability_docs))
    errors.extend(_lint_retry_reissue(doc, ability_docs))
    for n in doc.get("nodes", []):
        s = specs.get(n["speciality"])
        if s is None:
            errors.append(f"lint: node '{n['id']}' unknown speciality '{n['speciality']}'")
            continue
        if n.get("kind") == "subgraph":
            continue  # a subgraph node delegates; its abilities live in the child graph
        declared = set(n.get("abilities", []))
        missing_req = set(s["requires_abilities"]) - declared
        if missing_req:
            errors.append(f"lint: node '{n['id']}' missing required abilities {sorted(missing_req)}")
        unknown = declared - abilities
        if unknown:
            errors.append(f"lint: node '{n['id']}' unknown abilities {sorted(unknown)}")
        # `optional_abilities` was declared by 12 specialities and read by nothing
        # (2026-09-04 audit, D2-03). A speciality that lists what it may optionally
        # do has drawn a boundary; an ability outside it on a node of that
        # speciality is either a missing declaration or a role the node is not.
        if "optional_abilities" in s:
            allowed = set(s["requires_abilities"]) | set(s["optional_abilities"])
            outside = declared - allowed
            if outside:
                errors.append(
                    f"lint: node '{n['id']}' declares {sorted(outside)} but speciality "
                    f"'{n['speciality']}' allows only {sorted(allowed)} — add it to the "
                    "speciality's optional_abilities or pick the speciality that does this"
                )

    return (errors + _lint_v11(doc, root) + _lint_v14(doc) + _lint_v15(doc)
            + _lint_shapes(doc) + _lint_provenance(doc, root))


def _contract_gap_message(doc: dict) -> str | None:
    unmet = unconnected_keys(doc)
    if not unmet:
        return None
    return (
        f"verification asserts on {sorted(unmet)} which no node declares as an output "
        "and state.inputs does not supply"
    )


def _lint_v14(doc: dict) -> list[str]:
    """v1.4: the verification contract and the node I/O contracts must agree.

    An **error** at `apiVersion: agr/v1.4`; below that it is advisory and lives in
    `lint_advisories`, not here. Keeping advisories out of this list matters:
    every caller — `agr validate`, the `agr infuse` gate, the test suite — treats
    whatever `lint_graph` returns as fatal. An earlier draft returned warnings
    from here and instantly bricked mutation: `infuse` refused every graph with
    "infusion rejected by gate: warn: ...".
    """
    msg = _contract_gap_message(doc)
    if msg and doc.get("apiVersion") == "agr/v1.4":
        return [f"lint: {msg}"]
    return []


def _upstream_outputs(doc: dict) -> dict[str, set[str]]:
    """For each node, everything produced by a node that can reach it.

    Ancestors via any edge kind, with a visit guard for the retry loops the
    registry is full of. Fixed-point rather than a topological sort, because AGR
    graphs are deliberately cyclic.
    """
    by_id = {n["id"]: n for n in doc.get("nodes", [])}
    preds: dict[str, set[str]] = {nid: set() for nid in by_id}
    for e in doc.get("edges", []):
        if e["to"] in preds:
            preds[e["to"]].add(e["from"])
    up: dict[str, set[str]] = {nid: set() for nid in by_id}
    for _ in range(len(by_id) + 1):          # fixed point; graphs are small
        changed = False
        for nid in by_id:
            acc: set[str] = set()
            for p in preds[nid]:
                acc |= set(_out_names(by_id[p])) | up.get(p, set())
            if acc != up[nid]:
                up[nid], changed = acc, True
        if not changed:
            break
    return up


def silent_nodes(doc: dict) -> list[str]:
    """Nodes that something depends on but which declare no outputs.

    THE v1.5 gap. 103 of 346 nodes (29%) were contractually silent, and every one
    of them fed a downstream node. v1.4's lint asked whether *verification* had
    producers; nothing asked whether a node's **successors** have anything to
    consume.

    It matters because of what a live model does with silence. Told only to
    "return the keys this step is responsible for", `position-a` in
    `ab-test-analysis` answered the question literally —
    `{"keys": ["recomputed_effect", "claimed_effect"]}` — naming keys instead of
    producing values, and the judge downstream received an empty blackboard.

    Terminal nodes are exempt: a node nothing depends on owes nothing.
    """
    has_successor = {e["from"] for e in doc.get("edges", [])}
    return [
        n["id"] for n in doc.get("nodes", [])
        if n["id"] in has_successor
        and n.get("kind") != "subgraph"  # a phase delegates; the child declares
        and not _out_names(n)
    ]


def _silence_message(doc: dict) -> str | None:
    silent = silent_nodes(doc)
    if not silent:
        return None
    return (
        f"nodes {sorted(silent)} have outgoing edges but declare no outputs — "
        "their successors have nothing to consume"
    )


def joint_precondition_asserts(doc: dict) -> list[tuple[str, list[str]]]:
    """Asserts whose keys come from more than one producing node.

    Real but rare — 6 of 135. Advisory only: it is a documentation problem (the
    graph should say both facts must survive to the end), and inventing a
    `requires_all` field for six cases would be exactly the optional-and-unused
    surface this version exists to stop creating.
    """
    owner: dict[str, str] = {}
    for n in doc.get("nodes", []):
        for o in _out_names(n):
            owner.setdefault(o, n["id"])
    out: list[tuple[str, list[str]]] = []
    for v in doc.get("verification") or []:
        if "assert" not in v:
            continue
        producers = {owner[k] for k in asserted_keys(v["assert"]) if k in owner}
        if len(producers) > 1:
            out.append((v["assert"], sorted(producers)))
    return out


#: Fields no model can produce by generating — they name a fact that exists in
#: some system, or does not exist at all.
#: Facts that need a dataset, registry or corpus this repo does not ship. Distinct
#: from provenance strings: no binding *can* produce these, so a graph asserting
#: one is waiting for an integration rather than failing.
GROUND_TRUTH_FIELDS = {
    "matches_ownership_map", "matches_validated_set", "matches_transcript",
    "registry_id", "recomputed_effect", "claimed_effect", "paper", "section",
    "confirmation_id", "spdx",
}

PROVENANCE_FIELDS = {
    "source_url", "source_date", "log_id", "message_id", "exit_code", "file",
    "line", "quote_span", "playbook_ref", "scanner_evidence", "asset_map_ref",
    "advisory_url", "pr_url", "spdx", "citation",
}


def provenance_gaps(doc: dict, root: Path = ROOT) -> list[tuple[str, list[str]]]:
    """Asserts demanding provenance that no node on their path can obtain.

    `vendor-comparison-matrix` asserts
    `all(f.source_url and f.source_date for f in output.findings)` while its nodes
    declare `analyze`, `map_shard`, `reduce_merge`. Nothing can search. The
    contract demands citations from nodes given no way to obtain one — which is a
    graph-authoring defect, not a model failure, and it went undetected for nine
    versions because nothing ever asked.

    Returns `[(assert, [fields])]` for each such assert.
    """
    from .bindings import BUILTINS

    obtainable = {a for n in doc.get("nodes", []) for a in (n.get("abilities") or [])
                  if a in BUILTINS}
    gaps: list[tuple[str, list[str]]] = []
    for v in doc.get("verification") or []:
        expr = v.get("assert")
        if not expr:
            continue
        touched = asserted_keys_deep(expr)
        # A ground-truth fact is unobtainable regardless of what is bound — no
        # amount of `run_command` produces an on-call ownership map. The first
        # version of this detector was a list of URL/log/file names, so five
        # graphs needing a *dataset* were mislabelled "unsatisfiable by model".
        ground = sorted(GROUND_TRUTH_FIELDS & touched)
        if ground:
            gaps.append((expr, ground))
            continue
        wanted = sorted(PROVENANCE_FIELDS & touched)
        if wanted and not obtainable:
            gaps.append((expr, wanted))
    return gaps


def asserted_keys_deep(expr: str) -> set[str]:
    """Every attribute name an assert touches, including record fields.

    `asserted_keys` returns the blackboard keys — `findings`. This returns the
    fields *inside* them too, which is where provenance actually lives.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "get" and node.args
              and isinstance(node.args[0], ast.Constant)):
            out.add(str(node.args[0].value))
    return out


def _lint_provenance(doc: dict, root: Path = ROOT) -> list[str]:
    gaps = provenance_gaps(doc, root)
    if not gaps:
        return []
    msgs = [
        f"asserts on provenance {fields} but no node declares an ability that can "
        f"obtain one: {expr[:70]}"
        for expr, fields in gaps
    ]
    if doc.get("apiVersion") == "agr/v1.6":
        return [f"lint: {m}" for m in msgs]
    return []


def _lint_shapes(doc: dict) -> list[str]:
    """A declared shape must be well-formed. An unparseable one is worse than none."""
    from .shapes import declared

    errors: list[str] = []
    for n in doc.get("nodes", []):
        for name, expr in declared(n).items():
            if expr is None:
                continue
            try:
                _parse_shape(expr)
            except ShapeError as ex:
                errors.append(f"lint: node '{n['id']}' output '{name}' has a bad shape: {ex}")
    return errors


def _lint_v15(doc: dict) -> list[str]:
    msg = _silence_message(doc)
    if msg and doc.get("apiVersion") == "agr/v1.5":
        return [f"lint: {msg}"]
    return []


def lint_advisories(doc: dict) -> list[str]:
    """Non-fatal findings: true, worth surfacing, never a reason to refuse work.

    Kept strictly out of `lint_graph`, whose return value every caller treats as
    fatal — an earlier draft mixed them and `agr infuse` refused the whole
    registry with "rejected by gate: warn: ...".
    """
    out: list[str] = []
    gap = _contract_gap_message(doc)
    if gap and doc.get("apiVersion") != "agr/v1.4":
        out.append(f"warn: {gap} (declare them to reach apiVersion agr/v1.4)")
    silence = _silence_message(doc)
    if silence and doc.get("apiVersion") != "agr/v1.5":
        out.append(f"warn: {silence} (declare them to reach apiVersion agr/v1.5)")
    for expr, fields in provenance_gaps(doc):
        out.append(
            f"warn: asserts on provenance {fields} but no node declares an ability "
            f"that can obtain one — declare web_search/run_command/read_diff on the "
            f"producing node, or the contract is unsatisfiable by construction: {expr[:60]}"
        )
    for expr, producers in joint_precondition_asserts(doc):
        out.append(
            f"warn: assert spans keys from {producers} — both must survive to the "
            f"end for the check to be meaningful: {expr}"
        )
    return out


def validate_graph_file(path: Path, root: Path = ROOT) -> list[str]:
    doc = load(path)
    errors = validate_schema(doc, "graph")
    if not errors:
        # The motif is declared next door in `usecase.yaml`, not in the graph, so
        # the check that they agree needs both. Passed on the doc rather than
        # threaded through every lint signature.
        uc = path.parent / "usecase.yaml"
        if uc.exists():
            doc["__pattern__"] = load(uc).get("pattern")
        errors += lint_graph(doc, root)
        doc.pop("__pattern__", None)
    return errors
