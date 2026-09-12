"""An exported graph must *route* like the AGR graph it came from.

`agr adapt` / the `instantiate` MCP tool are the project's main consumer-facing
output, and until 2026-09-12 nothing checked their behaviour. The suite asserted
that emitted source parses, that it compiles, that the node *set* matches, and
that one router's condition helper evaluates correctly. None of that executes the
compiled app, so an adapter could wire the right nodes in the wrong order — a
fan-out emitted as a chain, a join that fires early, a router whose fallback is
unreachable — and every test would stay green (2026-09-12 audit, C12).

The method: run the graph through the AGR harness with its golden fixtures, then
execute the emitted LangGraph with node bodies that return *exactly what the
harness's node returned*. Behaviour is thereby held identical, so any difference
in which nodes run, or in what order, is the adapter's.
"""
from __future__ import annotations

import re

import pytest
import yaml

from agenticgraphs.adapters import emit_langgraph
from agenticgraphs.harness import MockRunner, run_graph
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import ROOT, load
from agenticgraphs.subgraphs import expand, has_subgraphs

pytest.importorskip("langgraph.graph", reason="install the `adapters` extra")

def _families() -> dict:
    """One graph per topology family the adapter has to get right.

    Derived from the registry rather than hardcoded, so a family gains coverage
    the moment a graph in it exists, and a hand-typed name cannot rot into a
    silent skip.
    """
    from agenticgraphs.registry import iter_graphs

    picks: dict = {}
    for path in iter_graphs():
        d = load(path)
        nodes, edges = d.get("nodes", []), d.get("edges", [])
        if has_subgraphs(d):
            picks.setdefault("composite (subgraph)", d["name"])
            continue  # its interesting shape is the expansion, tested as itself
        if any(n.get("kind") == "human" for n in nodes):
            picks.setdefault("human gate", d["name"])
        if any(e.get("kind") == "compensate" for e in edges):
            picks.setdefault("saga (compensate)", d["name"])
        if any(n.get("fan_out") for n in nodes):
            picks.setdefault("fan-out", d["name"])
        if any(n.get("join") for n in nodes):
            picks.setdefault("join", d["name"])
        if any(e.get("when") or e.get("condition") for e in edges):
            picks.setdefault("router", d["name"])
        if edges and all(sum(e["from"] == n["id"] for e in edges) <= 1 for n in nodes):
            picks.setdefault("linear pipeline", d["name"])
    return picks


FAMILIES = _families()

_RAISE = re.compile(r'^(\s*)raise NotImplementedError\(.*\)$')
_DEF = re.compile(r"^def (node_\w+)\(state: dict\) -> dict:")


def _stubbed(src: str, outputs: dict) -> str:
    """Rewrite each emitted node body to return what the harness's node returned.

    Substituting bodies is the point: with behaviour held identical between the
    two runtimes, the only thing left that can differ is the wiring.
    """
    out, current = [], None
    for line in src.splitlines():
        m = _DEF.match(line)
        if m:
            current = m.group(1)
        r = _RAISE.match(line)
        if r and current:
            out.append(f'{r.group(1)}return _AGR_STUB("{current}", state)')
        else:
            out.append(line)
    return "\n".join(out)


def _first_case(name: str) -> dict:
    return yaml.safe_load((find_graph(name).parent / "cases.yaml").read_text())["cases"][0]


def _harness_run(name: str):
    doc = load(find_graph(name))
    case = _first_case(name)
    seed = dict(case.get("inputs") or {})
    if case.get("goal"):
        seed["goal"] = case["goal"]
    gated = any(n.get("kind") == "human"
                for n in (expand(doc, ROOT) if has_subgraphs(doc) else doc)["nodes"])
    rep = run_graph(doc, MockRunner(case["node_outputs"]), root=ROOT,
                    auto_approve=gated, inputs=seed)
    return doc, rep, seed


def _execute_emitted(doc: dict, rep, seed: dict) -> list[str]:
    """Run the emitted LangGraph with harness-equivalent bodies; return its trace."""
    src = emit_langgraph(doc)
    visited: list[str] = []
    # Map the emitted function name back to the node id it was registered under.
    fn_to_id = dict(re.findall(r'g\.add_node\("([^"]+)", (node_\w+)\)', src)[::1] and
                    [(fn, nid) for nid, fn in
                     re.findall(r'g\.add_node\("([^"]+)", (node_\w+)\)', src)])
    pending = {nid: list(rep.frames_for(nid)) for nid in fn_to_id.values()}

    def stub(fn_name: str, state: dict) -> dict:
        nid = fn_to_id[fn_name]
        visited.append(nid)
        frames = pending.get(nid) or []
        return dict(frames.pop(0)["out"]) if frames else {}

    ns: dict = {"_AGR_STUB": stub}
    exec(compile(_stubbed(src, {}), f"<{doc['name']}-langgraph>", "exec"), ns)
    ns["app"].invoke(dict(seed))
    return visited


def _is_gated(doc: dict) -> bool:
    executable = expand(doc, ROOT) if has_subgraphs(doc) else doc
    return any(n.get("kind") == "human" for n in executable["nodes"])


@pytest.mark.parametrize(("family", "name"), sorted(FAMILIES.items()))
def test_emitted_langgraph_visits_the_nodes_the_harness_does(family, name):
    if find_graph(name) is None:
        pytest.fail(f"no graph named '{name}' — the {family} family has no representative")
    doc, rep, seed = _harness_run(name)
    if _is_gated(doc):
        pytest.skip("human-gated: the export refuses to sign itself — see the test below")
    visited = _execute_emitted(doc, rep, seed)

    assert set(visited) == set(rep.trace), (
        f"{name} ({family}): the compiled app visited {sorted(set(visited))}, "
        f"the harness ran {sorted(set(rep.trace))}"
    )


def test_a_human_gate_is_never_walked_past_in_the_export():
    """The one divergence that is correct: the harness can be told to auto-approve
    for CI; an exported graph has nobody to ask and must not proceed as if signed.

    `auto_approve` stamps a run `auto_approved` precisely so it is not read as a
    sign-off. The export has no equivalent, so it either raises (a `kind: human`
    node compiled to a raising stub) or halts at the gate's route — what it must
    never do is continue past an unsatisfied approval contract.
    """
    gated = [n for _f, n in sorted(FAMILIES.items())
             if find_graph(n) and _is_gated(load(find_graph(n)))]
    if not gated:
        pytest.skip("no human-gated representative in the families")
    for name in gated:
        doc, rep, seed = _harness_run(name)
        executable = expand(doc, ROOT) if has_subgraphs(doc) else doc
        gates = {n["id"] for n in executable["nodes"] if n.get("kind") == "human"}
        try:
            visited = _execute_emitted(doc, rep, seed)
        except PermissionError as e:
            assert "requires a person" in str(e)
            continue
        ran_gates = gates & set(visited)
        if not ran_gates:
            continue  # the case took a route that never asked for approval
        # A gate's successor may also be reachable without passing the gate — the
        # happy path in `invoice-reconciliation` goes verify -> post directly. So
        # this asks the narrower question: did anything run *after* the gate ran?
        last_gate = max(i for i, nid in enumerate(visited) if nid in ran_gates)
        after = visited[last_gate + 1:]
        assert not after, (
            f"{name}: the export ran {after} after reaching approval gate "
            f"'{visited[last_gate]}', which nobody signed"
        )


@pytest.mark.parametrize(("family", "name"), sorted(FAMILIES.items()))
def test_emitted_langgraph_respects_the_harness_ordering(family, name):
    """Order matters wherever one node reads what another wrote.

    Set equality would pass a fan-out emitted as a chain. This compares the
    relative order of every pair the harness ran sequentially, which is the part
    a downstream reader depends on, while leaving genuinely concurrent branches
    free to interleave.
    """
    doc, rep, seed = _harness_run(name)
    if _is_gated(doc):
        pytest.skip("human-gated: the export refuses to sign itself")
    visited = _execute_emitted(doc, rep, seed)

    executable = expand(doc, ROOT) if has_subgraphs(doc) else doc
    succ = {(e["from"], e["to"]) for e in executable.get("edges", [])
            if e.get("kind") != "compensate"}
    # Two things make an edge unorderable. A node the run revisited has no single
    # position; and a *back* edge — a generator-critic's `review -> produce` — is
    # declared in the opposite direction to the flow it belongs to. The emitter
    # identifies both by declaration order, so this uses the same rule it does.
    order = {n["id"]: i for i, n in enumerate(executable["nodes"])}
    once = {nid for nid in visited if visited.count(nid) == 1}
    pos = {nid: i for i, nid in enumerate(visited)}
    for a, b in succ:
        forward = order.get(a, 0) < order.get(b, 0)
        if forward and a in once and b in once and a in rep.trace and b in rep.trace:
            assert pos[a] < pos[b], (
                f"{name} ({family}): '{b}' ran before '{a}' in the compiled app, "
                f"but the graph declares {a} -> {b}"
            )


def test_a_router_takes_the_same_branch_not_just_a_valid_one():
    """The sharpest case: a router whose branch depends on an upstream value.

    `code-review-pipeline` fans to `security-review` only at `risk >= medium`.
    Its first golden case produces `risk: low`, so a correct export must skip it —
    an adapter that treated the conditional edge as unconditional would visit a
    superset and still pass a node-set check against the *declared* nodes.
    """
    doc, rep, seed = _harness_run("code-review-pipeline")
    visited = _execute_emitted(doc, rep, seed)

    assert "triage" in visited and "style-review" in visited
    assert "security-review" not in rep.trace, "fixture changed; pick another case"
    assert "security-review" not in visited, (
        "the compiled app took a branch the harness did not — the conditional "
        "edge is not being evaluated"
    )
