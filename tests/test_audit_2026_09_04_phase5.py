"""Phase 5 of the 2026-09-04 gap audit: adapters carry the contract.

Each test names the finding it closes (docs/plans/audit-gaps-2026-09-04.md).
"""
from __future__ import annotations

import pytest

from agenticgraphs.adapters import emit_autogen, emit_crewai, emit_langgraph
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import iter_graphs, load
from agenticgraphs.subgraphs import expand, has_subgraphs


def _asserts(doc):
    ex = expand(doc) if has_subgraphs(doc) else doc
    return [v["assert"] for v in ex.get("verification") or [] if "assert" in v]


# ------------------------------------------------------------------ D5-01 / R5-03


@pytest.mark.parametrize("emit", [emit_langgraph, emit_crewai, emit_autogen])
def test_every_assert_of_every_graph_appears_in_generated_source(emit):
    """30 asserts across 18 composites, zero in 36 generated files (D5-01)."""
    for gp in iter_graphs():
        doc = load(gp)
        src = emit(doc)
        for a in _asserts(doc):
            assert repr(a) in src, f"{doc['name']}: {emit.__name__} dropped {a!r}"
        assert "def check_contract(" in src


def test_generated_check_contract_evaluates_output_vocabulary_like_the_harness():
    langgraph = pytest.importorskip("langgraph.graph", reason="install the `adapters` extra")
    assert langgraph
    src = emit_langgraph(load(find_graph("code-review-pipeline")))
    ns: dict = {}
    exec(compile(src, "<crp>", "exec"), ns)
    good = {"verdict": "approve", "findings": [{"file": "a.py", "line": 3}]}
    assert ns["check_contract"](good) == []
    bad = {"verdict": "maybe", "findings": [{"file": "", "line": 3}]}
    failures = ns["check_contract"](bad)
    assert len(failures) == 2, failures
    assert ns["CONTRACT_COMMANDS"] and "gitleaks" in ns["CONTRACT_COMMANDS"][0][1]


def test_terminal_nodes_are_wrapped_so_the_contract_runs_when_flow_leaves():
    src = emit_langgraph(load(find_graph("code-review-pipeline")))
    assert "node_synthesize = _checked(node_synthesize)" in src
    assert "node_triage = _checked(node_triage)" not in src


# ------------------------------------------------------------------ D5-02 / R5-04


def test_fan_out_emits_one_send_per_shard():
    src = emit_langgraph(load(find_graph("vendor-comparison-matrix")))
    assert "from langgraph.types import Send" in src
    assert 'Send("fill", {**state, "shard": s' in src
    assert "def _fan_fill(state: dict):" in src


def test_a_graph_without_fan_out_does_not_import_send():
    assert "Send" not in emit_langgraph(load(find_graph("code-review-pipeline")))


def test_crewai_names_the_fan_out_it_cannot_express():
    src = emit_crewai(load(find_graph("vendor-comparison-matrix")))
    assert "fan_out over 'vendor_docs' is not expressible" in src


# ------------------------------------------------------------------ D5-03 / R5-05


def test_retries_become_a_wrapper_that_carries_reissue_effects():
    src = emit_langgraph(load(find_graph("bug-triage-and-fix")))
    assert "node_verify = _with_retries(node_verify, 2, True)" in src
    crew = emit_crewai(load(find_graph("bug-triage-and-fix")))
    assert "max_retry_limit=2,  # retries.max; reissue_effects: true" in crew


def test_the_approval_contract_guards_the_way_out_of_a_human_gate():
    doc = load(find_graph("feature-delivery-lifecycle"))
    src = emit_langgraph(doc)
    gate = next(n for n in doc["nodes"] if n.get("kind") == "human")
    assert f"if not _cond({gate['approval']['contract']!r}, state):" in src
    assert "return END  # approval not satisfied" in src


# ------------------------------------------------------------------ D5-04 / R5-01


def test_human_and_verifier_nodes_are_marked_in_both_targets():
    doc = load(find_graph("feature-delivery-lifecycle"))
    lg, cr = emit_langgraph(doc), emit_crewai(doc)
    assert "HUMAN GATE — a person signs this, never a model." in lg
    assert "raise PermissionError(\"human approval gate 'release-approval'" in lg
    assert "VERIFIER — grades the work" in lg
    assert "human_input=True," in cr and "HUMAN GATE: execute 'release-approval'" in cr
    assert "VERIFIER: execute" in cr


# ------------------------------------------------------------------ D5-05 / R5-02


def test_crewai_names_every_loop_it_drops():
    doc = load(find_graph("vendor-comparison-matrix"))
    src = emit_crewai(doc)
    order = {n["id"]: i for i, n in enumerate(doc["nodes"])}
    back = [e for e in doc["edges"] if order[e["to"]] <= order[e["from"]]]
    assert back, "fixture graph has no loop-back edge"
    for e in back:
        assert f"cannot re-enter '{e['to']}' from '{e['from']}'" in src


# ------------------------------------------------------------------ D5-06 / R5-06


def test_agr_instantiate_is_an_alias_of_adapt(capsys):
    from agenticgraphs.cli import main

    assert main(["instantiate", "verifier-swarm", "--target", "crewai"]) == 0
    out = capsys.readouterr().out
    assert "Crew(" in out and "def check_contract(" in out


def test_every_emitted_langgraph_module_still_builds():
    langgraph = pytest.importorskip("langgraph.graph", reason="install the `adapters` extra")
    assert langgraph
    for name in ("vendor-comparison-matrix", "feature-delivery-lifecycle", "bug-triage-and-fix"):
        src = emit_langgraph(load(find_graph(name)))
        ns: dict = {}
        exec(compile(src, f"<{name}>", "exec"), ns)
        assert ns["app"].get_graph()
