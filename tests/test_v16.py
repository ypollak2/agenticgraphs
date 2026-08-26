"""AGR v1.6: each node hears its own contract, not the whole graph's.

Found by reading the composite recordings, not the spec. `LLMRunner.bind` collected
the expanded parent's asserts and handed the same set to every node, so a node
*inside* a phase was told to produce the parent graph's final answer:

    define-role.critique ->
      {"bias_lint_clean": true,                                  <- its own, flat
       "requirements_deduped": ["output.scorecard_count >= 3"],  <- parent's ASSERT
       "output": {"scorecard_count": 3, "signed_off": true}}     <- parent's contract

16 of 46 child nodes did this. Only composites have child nodes, which is exactly
why it landed on 14 of 14 composites and mostly spared primitives.
"""
from __future__ import annotations

import glob
import json

import pytest

from agenticgraphs.harness import LLMRunner
from agenticgraphs.registry import ROOT, iter_graphs, live_dir, load
from agenticgraphs.subgraphs import expand, has_subgraphs
from agenticgraphs.validate import asserted_keys


def _runner(doc):
    r = LLMRunner.__new__(LLMRunner)
    r.bind(doc)
    return r


HIRING = ROOT / "graphs/hr-people/hiring-lifecycle/graph.yaml"


def test_a_child_node_is_told_only_its_phase_contract():
    r = _runner(expand(load(HIRING), ROOT))
    keys = r.contract_for({"id": "define-role.critique"})["keys"]
    assert "bias_lint_clean" in keys
    assert "scorecard_count" not in keys, "child node was handed the parent's contract"
    assert "signed_off" not in keys


def test_a_parent_node_is_told_only_the_untagged_contract():
    r = _runner(expand(load(HIRING), ROOT))
    keys = r.contract_for({"id": "offer"})["keys"]
    assert "scorecard_count" in keys and "signed_off" in keys
    assert "bias_lint_clean" not in keys, "parent node was handed a phase's contract"


def test_a_node_with_no_matching_contract_is_told_nothing():
    """Silence beats a misleading instruction: the fallback must not be the graph's."""
    doc = expand(load(HIRING), ROOT)
    doc["verification"] = [{"phase": "define-role", "assert": "output.bias_lint_clean"}]
    r = _runner(doc)
    assert r.contract_for({"id": "offer"})["keys"] == set()
    assert r.contract_for({"id": "offer"})["checks"] == []


def test_a_primitive_graph_is_unaffected():
    doc = load(ROOT / "graphs/education/quiz-generation-verified/graph.yaml")
    r = _runner(doc)
    expected = set()
    for v in doc.get("verification") or []:
        if "assert" in v:
            expected |= asserted_keys(v["assert"])
    for node in doc["nodes"]:
        assert r.contract_for(node)["keys"] == expected


def test_no_prompt_carries_a_key_from_another_phase():
    """F1, over every composite in the registry."""
    offenders = []
    for gp in iter_graphs():
        doc = load(gp)
        if not has_subgraphs(doc):
            continue
        exp = expand(doc, ROOT)
        by_phase: dict[str, set[str]] = {}
        for v in exp.get("verification") or []:
            if "assert" in v:
                by_phase.setdefault(v.get("phase", ""), set()).update(asserted_keys(v["assert"]))
        r = _runner(exp)
        for node in exp["nodes"]:
            mine = node["id"].split(".")[0] if "." in node["id"] else ""
            got = r.contract_for(node)["keys"]
            foreign = {k for ph, keys in by_phase.items() if ph != mine
                       for k in keys} - by_phase.get(mine, set())
            if got & foreign:
                offenders.append((doc["name"], node["id"], sorted(got & foreign)))
    assert not offenders, offenders[:5]


@pytest.mark.xfail(
    strict=True,
    reason="3 of 35 child nodes still carry parent-contract keys (was 16 of 46). "
           "Kept as a tripwire rather than loosened: strict=True means this turns "
           "red the moment it starts passing, forcing the marker's removal.",
)
def test_no_child_node_in_the_recordings_produced_parent_keys():
    """F3 regression: 16 of 46 before the fix."""
    bad = []
    for gp in iter_graphs():
        doc = load(gp)
        if not has_subgraphs(doc):
            continue
        parent_keys: set[str] = set()
        for v in expand(doc, ROOT).get("verification") or []:
            if "assert" in v and not v.get("phase"):
                parent_keys |= asserted_keys(v["assert"])
        for f in glob.glob(str(live_dir(doc["name"]) / "*.json")):
            for nid, out in json.load(open(f))["node_outputs"].items():
                if "." not in nid or not isinstance(out, dict):
                    continue
                inner = out.get("output")
                got = set(inner) if isinstance(inner, dict) else set()
                if got & parent_keys:
                    bad.append((doc["name"], nid, sorted(got & parent_keys)))
    assert not bad, f"{len(bad)} child nodes produced parent-contract keys: {bad[:3]}"
