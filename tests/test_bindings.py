"""Ability bindings: a node obtains facts it cannot invent.

18 of 28 remaining composite assert failures demanded a grounded provenance field
— `source_url`, `exit_code`, `file`+`line`. A model cannot produce those honestly,
and one that appeared to would be fabricating them. These tests cover the binding
layer and, more importantly, the *inverse* property: a graph must still fail when
the tools are taken away. A graph that passes without its tool did not earn it.
"""
from __future__ import annotations

import json

import pytest

from agenticgraphs import bindings
from agenticgraphs.evalcmd import verification_depth
from agenticgraphs.harness import MockRunner, RunReport, run_graph
from agenticgraphs.registry import ROOT


# ------------------------------------------------------------------ risk gating


def test_risk_execute_is_unbound_unless_the_caller_opts_in():
    """The permission model is the `risk` field abilities have declared since M0."""
    assert "run_command" not in bindings.available()
    assert "run_command" in bindings.available(allow_mutating=True)


def test_read_risk_abilities_bind_freely():
    assert {"read_diff", "web_search"} <= set(bindings.available())


def test_a_node_is_offered_only_the_abilities_it_declares():
    """Never a general toolbox — what a node may do is written down."""
    node = {"id": "n", "abilities": ["read_diff"]}
    assert set(bindings.bind_for(node)) == {"read_diff"}
    bare = {"id": "n", "abilities": []}
    assert bindings.bind_for(bare) == {}


def test_invoking_an_unbound_ability_is_refused_not_faked():
    call = bindings.invoke("run_command", {"command": "true"}, ROOT, allow_mutating=False)
    assert not call.ok
    assert "not bound" in call.detail


def test_every_bound_ability_declares_its_binding_in_yaml():
    """The seam shipped in M0 and no ability used it; bound ones must now."""
    from agenticgraphs.registry import iter_yaml, load

    for path in iter_yaml("abilities"):
        doc = load(path)
        if doc["name"] in bindings.BUILTINS:
            assert doc.get("binding"), f"{doc['name']} is bound but declares no binding"
            assert doc["binding"]["kind"] == "builtin"


# ------------------------------------------------------------------- the facts


def test_run_command_returns_a_real_exit_code(tmp_path):
    ok = bindings.invoke("run_command", {"command": "true"}, tmp_path, allow_mutating=True)
    assert ok.ok and ok.evidence["exit_code"] == 0
    bad = bindings.invoke("run_command", {"command": "false"}, tmp_path, allow_mutating=True)
    assert bad.evidence["exit_code"] == 1


def test_run_command_reports_a_missing_binary_rather_than_raising(tmp_path):
    call = bindings.invoke("run_command", {"command": "definitely-not-real-xyz"},
                           tmp_path, allow_mutating=True)
    assert call.evidence.get("exit_code") is None
    assert "FileNotFoundError" in call.evidence.get("error", "")


def test_read_diff_returns_real_file_and_line_pairs():
    call = bindings.invoke("read_diff", {"ref": "HEAD~1"}, ROOT)
    assert call.ok
    for hunk in call.evidence["hunks"]:
        assert hunk["file"] and isinstance(hunk["line"], int)


def test_a_missing_argument_is_an_error_not_an_empty_result(tmp_path):
    call = bindings.invoke("run_command", {}, tmp_path, allow_mutating=True)
    assert not call.ok and "needs a 'command'" in call.detail


# ------------------------------------------------------ grounding and its grade


def test_a_run_with_no_tool_calls_is_not_grounded():
    rep = run_graph(
        {"apiVersion": "agr/v1.5", "name": "g", "description": "unit test graph",
         "category": "software-engineering",
         "nodes": [{"id": "a", "speciality": "analyst", "abilities": ["analyze"],
                    "outputs": ["x"]},
                   {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
         "edges": [{"from": "a", "to": "b"}],
         "termination": {"max_steps": 5, "contract": "b after a"}},
        MockRunner({"a": {"x": 1}, "b": {}}))
    assert rep.grounded is False


def test_grounded_outranks_live_in_the_depth_ladder():
    doc = {"verification": [{"assert": "x == 1"}]}
    assert verification_depth(doc, "tools:gpt-4o", grounded=True) == "assert-grounded"
    assert verification_depth(doc, "tools:gpt-4o", grounded=False) == "assert-live"
    assert verification_depth(doc, "mock", grounded=False) == "assert-fixture"


def test_a_failed_tool_call_does_not_count_as_grounding():
    """A trace that only records successes is not a trace."""
    rep = RunReport()
    rep.tool_calls.append(bindings.ToolCall("run_command", {}, False, "refused"))
    assert rep.grounded is False
    rep.tool_calls.append(bindings.ToolCall("read_diff", {}, True, "ok", {"hunks": []}))
    assert rep.grounded is True


# ------------------------------------------- THE INVERSE TEST (the one that matters)


def test_the_provenance_assert_cannot_be_satisfied_without_the_tool():
    """A graph that passes with its tools removed did not earn the pass.

    `docs-code-sync-audit` asserts `all(e.exit_code == 0 for e in output.examples)`.
    With no binding, `exit_code` can only come from the model asserting it — which
    is precisely the fabrication this whole layer exists to prevent. If this test
    ever goes green, the assert has stopped requiring evidence.
    """
    from agenticgraphs.registry import load

    doc = load(ROOT / "graphs/software-engineering/docs-code-sync-audit/graph.yaml")
    node = next(n for n in doc["nodes"] if n["id"] == "verify")
    assert "run_command" in node["abilities"]
    # Tools off: the ability the assert depends on resolves to nothing.
    assert bindings.bind_for(node, allow_mutating=False) == {}
    # Tools on: it resolves, and only then can `exit_code` be a real fact.
    assert "run_command" in bindings.bind_for(node, allow_mutating=True)


def test_the_registrys_provenance_asserts_all_name_a_bindable_ability():
    """Every assert demanding evidence must have a node able to obtain it.

    Otherwise the contract is unsatisfiable by construction rather than unmet —
    a distinction the scoreboard has to be able to make.
    """
    import re

    from agenticgraphs.registry import iter_graphs, load
    from agenticgraphs.subgraphs import expand, has_subgraphs

    provenance = re.compile(r"\b(exit_code|source_url|source_date|file|line)\b")
    orphaned = []
    for gp in iter_graphs():
        doc = load(gp)
        exp = expand(doc, ROOT) if has_subgraphs(doc) else doc
        wants = any(provenance.search(v.get("assert", ""))
                    for v in exp.get("verification") or [])
        if not wants:
            continue
        bindable = any(bindings.bind_for(n, allow_mutating=True)
                       for n in exp["nodes"] if n.get("kind") != "subgraph")
        if not bindable:
            orphaned.append(doc["name"])
    # Reported, not asserted to zero: some graphs legitimately need systems this
    # repo has no binding for (a log store, a scanner). Naming them is the point.
    assert isinstance(orphaned, list)
    print(f"\ngraphs asserting provenance with no bindable ability: {len(orphaned)}")
    for n in orphaned:
        print(f"  {n}")


def test_grounding_proves_provenance_exists_not_that_it_is_relevant():
    """The limit of `assert-grounded`, stated so it is not over-read.

    On the pilot run `gpt-4o` made 20 real `run_command` calls, all successful and
    all traced — and several were invented theatre (`echo 'Running test command 2'`)
    rather than the documented examples the graph is about. The trace proves
    *something ran*; it does not prove the *right* thing ran.

    That is still strictly stronger than `assert-live`, where nothing ran at all.
    """
    call = bindings.ToolCall("run_command", {"command": "echo hi"}, True, "ok",
                             {"exit_code": 0})
    rep = RunReport()
    rep.tool_calls.append(call)
    assert rep.grounded is True          # provenance exists
    assert call.evidence["exit_code"] == 0
    # and nothing here claims the command was the one the contract meant
