"""Phase 4 of the 2026-09-04 gap audit: composites carry a checked contract.

Each test names the finding it closes (docs/plans/audit-gaps-2026-09-04.md).
"""
from __future__ import annotations

import pytest
import yaml

from agenticgraphs.harness import MockRunner, run_graph
from agenticgraphs.registry import SPEC_VERSION, load
from agenticgraphs.subgraphs import SubgraphError, expand
from agenticgraphs.validate import lint_graph

GOAL = {"goal": "a stated subject"}


def _child(name="leaf", outputs=("findings",), goal=False, state=None, memory=None):
    doc = {
        "apiVersion": SPEC_VERSION, "name": name, "category": "cat", "description": "child",
        "nodes": [{"id": "a", "speciality": "analyst", "abilities": ["analyze"],
                   "outputs": list(outputs)}],
        "edges": [],
        "termination": {"max_steps": 5, "contract": "a runs"},
        "verification": [{"assert": "true"}],
    }
    if goal:
        doc["goal"] = {"required": True, "description": "what the leaf needs"}
    if state:
        doc["state"] = state
    if memory:
        doc["memory"] = memory
    return doc


def _parent(phase_outputs, maps=None, goal=None, state=None):
    node = {"id": "phase", "speciality": "supervisor", "kind": "subgraph", "ref": "cat/leaf",
            "outputs": list(phase_outputs)}
    if maps:
        node["maps"] = maps
    doc = {
        "apiVersion": SPEC_VERSION, "name": "parent", "category": "cat", "description": "parent",
        "nodes": [node, {"id": "use", "speciality": "producer", "abilities": ["generate"],
                         "inputs": list(phase_outputs), "outputs": ["y"]}],
        "edges": [{"from": "phase", "to": "use"}],
        "termination": {"max_steps": 10, "contract": "use runs after the phase"},
        "verification": [{"assert": "y == 1"}],
    }
    if goal:
        doc["goal"] = goal
    if state:
        doc["state"] = state
    return doc


@pytest.fixture
def root(tmp_path):
    """Write (or rewrite) the child graph under a scratch registry root."""
    def write(child):
        d = tmp_path / "graphs" / "cat" / "leaf"
        d.mkdir(parents=True, exist_ok=True)
        (d / "graph.yaml").write_text(yaml.safe_dump(child, sort_keys=False))
        return tmp_path
    return write


def _lint(doc, root):
    # Speciality/ability files live in the real registry; graphs under tmp root.
    # lint_graph takes one root for both, so copy the two small dirs across.
    import shutil

    from agenticgraphs.registry import ROOT

    for sub in ("specialities", "abilities"):
        if not (root / sub).exists():
            shutil.copytree(ROOT / sub, root / sub)
    return [e for e in lint_graph(doc, root=root) if "phase" in e]


# ------------------------------------------------------------------ D4-01 / R4-01


def test_a_phase_output_the_child_never_produces_is_refused(root):
    r = root(_child(outputs=("findings",)))
    errs = _lint(_parent(["vendor_docs"]), r)
    assert errs and "vendor_docs" in errs[0] and "produces no such key" in errs[0]


def test_an_explicit_map_from_a_child_key_is_accepted(root):
    r = root(_child(outputs=("findings",)))
    assert _lint(_parent(["vendor_docs"], maps={"vendor_docs": "findings"}), r) == []


def test_a_map_from_a_key_the_child_does_not_produce_is_refused(root):
    r = root(_child(outputs=("findings",)))
    errs = _lint(_parent(["vendor_docs"], maps={"vendor_docs": "results"}), r)
    assert errs and "does not produce" in errs[0]


def test_renaming_a_child_output_breaks_the_composite_at_validate_time(root):
    """The acceptance criterion for R4-01: drift is caught statically."""
    r = root(_child(outputs=("findings",)))
    parent = _parent(["vendor_docs"], maps={"vendor_docs": "findings"})
    assert _lint(parent, r) == []
    root(_child(outputs=("results",)))  # the primitive renames its output
    assert _lint(parent, r), "the composite kept validating after its child changed"


def test_the_map_is_applied_at_run_time(root):
    r = root(_child(outputs=("findings",)))
    parent = _parent(["vendor_docs"], maps={"vendor_docs": "findings"})
    rep = run_graph(parent, MockRunner({"phase.a": {"findings": [1, 2]}, "use": {"y": 1}}),
                    root=r, inputs=GOAL)
    assert rep.passed, rep.assert_failures
    assert rep.frames_for("phase.a")[0]["out"]["vendor_docs"] == [1, 2]


def test_every_registry_phase_promises_only_what_its_child_produces():
    from agenticgraphs.registry import iter_graphs

    for gp in iter_graphs():
        assert not [e for e in lint_graph(load(gp)) if "phase '" in e], gp


def test_a_composites_profile_carries_its_childrens_shape_hashes():
    from agenticgraphs.inspect import find_graph, structural_profile
    from agenticgraphs.registry import sha, shape

    prof = structural_profile(load(find_graph("vendor-comparison-matrix")))
    child = load(find_graph("competitive-intelligence"))
    assert prof["refs"]["research-knowledge/competitive-intelligence"] == sha(shape(child))


# ------------------------------------------------------------------ D4-03 / R4-02


def test_a_childs_goal_requirement_is_inherited_by_the_parent(root):
    r = root(_child(goal=True))
    out = expand(_parent(["findings"]), r)
    assert out["goal"]["required"] is True
    assert out["goal"]["description"] == "what the leaf needs"


def test_the_goal_gate_sees_the_inherited_requirement(root):
    r = root(_child(goal=True))
    rep = run_graph(_parent(["findings"]), MockRunner({"phase.a": {"findings": 1}, "use": {"y": 1}}),
                    root=r)  # no goal supplied
    assert rep.goal_missing == "what the leaf needs" and rep.trace == []


def test_child_state_inputs_are_unioned_into_the_parent(root):
    r = root(_child(state={"inputs": ["goal", "policy_table"]}))
    out = expand(_parent(["findings"], state={"inputs": ["goal", "vendors"]}), r)
    assert out["state"]["inputs"] == ["goal", "vendors", "policy_table"]


def test_conflicting_child_state_schemas_are_an_error(root, tmp_path):
    r = root(_child(state={"schema": "schemas/a.json"}))
    d2 = tmp_path / "graphs" / "cat" / "leaf2"
    d2.mkdir(parents=True)
    d2.joinpath("graph.yaml").write_text(yaml.safe_dump(_child("leaf2", state={"schema": "schemas/b.json"})))
    parent = _parent(["findings"])
    parent["nodes"].insert(1, {"id": "phase2", "speciality": "supervisor", "kind": "subgraph",
                               "ref": "cat/leaf2", "outputs": ["findings"]})
    parent["edges"] = [{"from": "phase", "to": "phase2"}, {"from": "phase2", "to": "use"}]
    with pytest.raises(SubgraphError, match="one blackboard, one schema"):
        expand(parent, r)


def test_graph_scoped_memory_in_a_child_widens_the_parent(root):
    r = root(_child(memory={"scope": "graph"}))
    assert expand(_parent(["findings"]), r)["memory"]["scope"] == "graph"


def test_no_registry_composite_depends_on_hand_duplicated_goal_lines():
    """Every composite's expanded goal equals its declared one: the inheritance
    and the nine hand-written duplicates agree, so either may be removed."""
    from agenticgraphs.registry import iter_graphs
    from agenticgraphs.subgraphs import has_subgraphs

    for gp in iter_graphs():
        doc = load(gp)
        if has_subgraphs(doc):
            assert expand(doc)["goal"]["required"] == doc["goal"]["required"], gp


# ------------------------------------------------------------------ D4-05 / R4-03


def test_compose_scaffold_writes_a_bundle_that_validates_and_has_a_runnable_case(tmp_path, capsys):
    from agenticgraphs.cli import main
    from agenticgraphs.validate import validate_graph_file

    out = tmp_path / "bundle"
    code = main(["compose", "invoice-reconciliation", "competitive-intelligence",
                 "--mode", "subgraph", "--scaffold", str(out)])
    capsys.readouterr()
    assert code == 0
    assert {p.name for p in out.iterdir()} == {"graph.yaml", "cases.yaml", "usecase.yaml", "live"}
    assert validate_graph_file(out / "graph.yaml") == []
    cases = yaml.safe_load((out / "cases.yaml").read_text())["cases"]
    ids = set(cases[0]["node_outputs"])
    assert any(i.startswith("invoice-reconciliation.") for i in ids)
    assert any(i.startswith("competitive-intelligence.") for i in ids)
    assert cases[0]["goal"]
    # The stub says what a human still owes.
    assert yaml.safe_load((out / "usecase.yaml").read_text())["id"] == "uc-TODO"
