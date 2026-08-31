"""AGR v1.5: every node that something depends on declares what it produces.

The gap this closes was 103 of 346 nodes (29%) declaring nothing while every one
of them fed a downstream node. It stayed invisible for four versions because a
fixture supplies whatever the runtime owes — only a live model, told "return the
keys this step is responsible for", answered the question literally and returned
key *names* where values belonged.
"""
from __future__ import annotations

import pytest
import yaml

from agenticgraphs.evalcmd import case_inputs
from agenticgraphs.harness import LLMRunner, MockRunner, run_graph
from agenticgraphs.registry import ROOT, cases_path, iter_graphs, load
from agenticgraphs.subgraphs import expand, has_subgraphs
from agenticgraphs.validate import (
    joint_precondition_asserts,
    lint_advisories,
    lint_graph,
    silent_nodes,
)


def _g(**kw):
    doc = {
        "apiVersion": "agr/v1.5",
        "name": "unit-test-graph",
        "description": "a graph used only by unit tests",
        "category": "software-engineering",
        "nodes": [
            {"id": "a", "speciality": "analyst", "abilities": ["analyze"], "outputs": ["x"]},
            {"id": "b", "speciality": "producer", "abilities": ["generate"], "outputs": ["y"]},
        ],
        "edges": [{"from": "a", "to": "b"}],
        "termination": {"max_steps": 10, "contract": "b runs after a"},
    }
    doc.update(kw)
    return doc


# ------------------------------------------------------------------ silent nodes


def test_a_node_with_a_successor_must_declare_an_output():
    doc = _g()
    del doc["nodes"][0]["outputs"]
    assert silent_nodes(doc) == ["a"]
    assert any("nothing to consume" in e and e.startswith("lint:") for e in lint_graph(doc))


def test_a_terminal_node_owes_nothing():
    """A node nothing depends on has no successor to starve."""
    doc = _g()
    del doc["nodes"][1]["outputs"]          # `b` is terminal
    assert silent_nodes(doc) == []
    assert not [e for e in lint_graph(doc) if "nothing to consume" in e]


def test_a_subgraph_phase_delegates_rather_than_declaring():
    doc = _g(nodes=[{"id": "p", "speciality": "supervisor", "kind": "subgraph",
                     "ref": "software-engineering/legacy-refactor"},
                    {"id": "b", "speciality": "producer", "abilities": ["generate"],
                     "outputs": ["y"]}],
             edges=[{"from": "p", "to": "b"}],
             verification=[{"assert": "y is not None"}])
    assert silent_nodes(doc) == []


def test_silence_is_advisory_below_v15():
    """The channel split from v1.4: advisories never reach the fatal list."""
    doc = _g(apiVersion="agr/v1.4")
    del doc["nodes"][0]["outputs"]
    assert not [e for e in lint_graph(doc) if "nothing to consume" in e]
    assert any("nothing to consume" in w for w in lint_advisories(doc))


def test_no_registry_node_is_silent():
    """E1: 103 -> 0, checked on the expanded graph, which is what executes."""
    offenders = {}
    for gp in iter_graphs():
        doc = load(gp)
        exp = expand(doc, ROOT) if has_subgraphs(doc) else doc
        if silent := silent_nodes(exp):
            offenders[doc["name"]] = silent
    assert not offenders, offenders


def test_every_registry_graph_declares_the_current_spec_version():
    """No graph is left behind by a migration.

    This asserted `agr/v1.5` literally until v1.7, which meant every version bump
    had to edit the test that exists to catch an incomplete bump. It now reads the
    one source of truth, so the invariant survives the number changing.
    """
    from agenticgraphs.registry import SPEC_VERSION

    stragglers = [load(gp)["name"] for gp in iter_graphs()
                  if load(gp)["apiVersion"] != SPEC_VERSION]
    assert not stragglers, stragglers


def test_no_registry_graph_declares_v16():
    """v1.6 arms the hard provenance lint (`validate._lint_provenance`).

    It is a per-graph opt-in, taken deliberately after reviewing that graph's
    provenance asserts. The v1.7 goal migration bumped all 83 graphs at once; had
    it routed them through v1.6, `clinical-protocol-lifecycle` would have failed on
    `registry_id` — a ground-truth field no binding here can obtain — while the
    change under review was about goals.
    """
    armed = [load(gp)["name"] for gp in iter_graphs() if load(gp)["apiVersion"] == "agr/v1.6"]
    assert not armed, armed


# ---------------------------------------------------- inputs must be REACHABLE


def test_an_input_produced_only_downstream_is_unreachable():
    """v1.1 checked set membership: 'does this key exist anywhere in the graph'.

    That passes even when the only producer runs strictly after the consumer, so
    the value can never arrive. Only checkable now that every dependent node has
    an output to be reachable *from*.
    """
    doc = _g()
    doc["nodes"][0]["inputs"] = ["y"]      # `y` is produced by `b`, downstream of `a`
    assert any("no node reaching it outputs" in e for e in lint_graph(doc))


def test_an_input_produced_upstream_is_fine():
    doc = _g()
    doc["nodes"][1]["inputs"] = ["x"]
    assert not [e for e in lint_graph(doc) if "reaching it" in e]


def test_reachability_terminates_on_a_retry_loop():
    """AGR graphs are deliberately cyclic; the fixed point must still settle."""
    doc = _g(edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "a", "when": "retry"}])
    doc["nodes"][0]["inputs"] = ["y"]      # reachable via the back-edge
    assert not [e for e in lint_graph(doc) if "reaching it" in e]


def test_no_registry_graph_has_an_unreachable_input():
    bad = {load(gp)["name"]: [e for e in lint_graph(load(gp)) if "reaching it" in e]
           for gp in iter_graphs() if any("reaching it" in e for e in lint_graph(load(gp)))}
    assert not bad, bad


# --------------------------------------------------------- joint preconditions


def test_an_assert_spanning_two_producers_is_flagged_advisory():
    """Real but rare — 6 of 135. A documentation problem, not new machinery."""
    doc = _g(verification=[{"assert": "x > y"}])
    spans = joint_precondition_asserts(doc)
    assert spans == [("x > y", ["a", "b"])]
    assert any("both must survive to the end" in w for w in lint_advisories(doc))
    assert not [e for e in lint_graph(doc) if "survive to the end" in e]


def test_a_single_producer_assert_is_not_flagged():
    doc = _g(verification=[{"assert": "x > 0"}])
    assert joint_precondition_asserts(doc) == []


# ------------------------------------------------------------------ the prompt


def test_the_prompt_asks_for_values_not_key_names():
    """D2. The old wording — "return the keys this step is responsible for" — is a
    question about the node's *job*, and models answered it as one:
    `{"keys": ["recomputed_effect", "claimed_effect"]}`.
    """
    import inspect

    src = inspect.getsource(LLMRunner.run)
    assert "concrete values" in src
    assert "never key names" in src
    # The old wording survives only in the comment explaining why it was wrong.
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("keys this step is responsible for" in ln for ln in code)


def test_bind_collects_the_keys_the_contract_asserts_on():
    runner = LLMRunner.__new__(LLMRunner)
    runner.bind(_g(verification=[{"assert": "x > 0 and output.verdict == 'ok'"}]))
    assert runner.asserted == {"x", "verdict"}


# ------------------------------------------------------------------- registry


def test_whole_registry_still_passes_its_golden_cases():
    total = passed = 0
    for gp in iter_graphs():
        doc = load(gp)
        for case in yaml.safe_load(
                (cases_path(doc["name"])).read_text())["cases"]:
            total += 1
            passed += run_graph(doc, MockRunner(case["node_outputs"]), root=ROOT,
                                inputs=case_inputs(case)).passed
    assert passed == total, f"{total - passed} of {total} failing"


@pytest.mark.parametrize("motif_node", ["map", "work", "execute"])
def test_template_worker_nodes_declare_a_result(motif_node):
    """20 nodes across map-reduce, parallel-swarm and PEV declared nothing and had
    a `{}` fixture — the shape was copied before anyone asked what it hands on.
    """
    for gp in iter_graphs():
        doc = load(gp)
        node = next((n for n in doc["nodes"] if n["id"] == motif_node), None)
        if node is None or node.get("kind") == "subgraph":
            continue
        if node["id"] in {e["from"] for e in doc["edges"]}:
            assert node.get("outputs"), f"{doc['name']}/{motif_node}"
