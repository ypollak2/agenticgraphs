"""Phase 3 of the 2026-09-04 gap audit: the runtime and linter tell the truth.

Each test names the finding it closes (docs/plans/audit-gaps-2026-09-04.md) and
guards the property, not the patch.
"""
from __future__ import annotations

import time

from agenticgraphs.harness import HumanGateRequired, MockRunner, RunReport, run_graph
from agenticgraphs.registry import SPEC_VERSION

GOAL = {"goal": "a stated subject, so the graph does not invent one"}


def _g(**kw):
    doc = {
        "apiVersion": SPEC_VERSION,
        "name": "unit-test-graph",
        "description": "a graph used only by unit tests",
        "category": "software-engineering",
        "nodes": [
            {"id": "a", "speciality": "analyst", "abilities": ["analyze"], "outputs": ["x"]},
            {"id": "b", "speciality": "producer", "abilities": ["generate"], "outputs": ["y"]},
        ],
        "edges": [{"from": "a", "to": "b"}],
        "termination": {"max_steps": 20, "contract": "b runs after a"},
        "verification": [{"assert": "y == 2"}],
    }
    doc.update(kw)
    return doc


# ------------------------------------------------------------------ D3-03 / R3-01


class _Unparseable:
    """A runner whose reply for `a` has no JSON object, then recovers."""

    name = "mock"

    def __init__(self):
        self.calls = 0

    def run(self, node, bb):
        if node["id"] == "a":
            self.calls += 1
            if self.calls == 1:
                from agenticgraphs.harness import extract_json
                return extract_json("Sure! Here is my analysis, in prose only.")
            return {"x": 1}
        return {"y": 2}


def test_a_reply_that_does_not_parse_is_a_typed_failure_not_a_crash():
    doc = _g()
    doc["nodes"][0]["retries"] = {"max": 1}
    rep = run_graph(doc, _Unparseable(), inputs=GOAL)
    assert rep.parse_failures and rep.parse_failures[0].startswith("a: ")
    assert rep.retries_used == 1, "a parse failure must be retryable like any node error"
    assert rep.passed, rep.assert_failures  # recovered on retry
    assert "parse" in rep.failure_kinds


def test_an_unrecovered_parse_failure_fails_the_run_with_its_kind_named():
    rep = run_graph(_g(), _Unparseable(), inputs=GOAL)  # no retries
    assert rep.parse_failures
    assert not rep.passed
    assert "parse" in rep.failure_kinds


class _Refuses(MockRunner):
    def approve(self, node, bb, auto_approve=False):
        if not auto_approve:
            raise HumanGateRequired(f"node '{node['id']}' is a human approval gate")
        return {"signed_off": True}


def _gated():
    return _g(
        nodes=[{"id": "work", "speciality": "producer", "abilities": ["generate"], "outputs": ["y"]},
               {"id": "gate", "speciality": "approver", "abilities": ["approve"], "kind": "human",
                "approval": {"contract": "signed_off == true"}, "outputs": ["signed_off: bool"]},
               {"id": "ship", "speciality": "release-manager", "abilities": ["cut_release"]}],
        edges=[{"from": "work", "to": "gate"}, {"from": "gate", "to": "ship"},
               {"from": "ship", "to": "work", "kind": "compensate"}],
        verification=[{"assert": "output.signed_off == true"}],
    )


def test_a_gate_nobody_can_sign_is_a_typed_outcome_not_an_exception():
    """`HumanGateRequired` escaped `run_graph` uncaught; `agr eval` crashed and
    the recorder wrote nothing (D3-03)."""
    rep = run_graph(_gated(), _Refuses({"work": {"y": 2}}), inputs=GOAL)
    assert rep.gate_refused.startswith("gate: ")
    assert "ship" not in rep.trace
    assert not rep.passed
    assert rep.failure_kinds == ["gate"] or "gate" in rep.failure_kinds


def test_failure_kinds_is_empty_on_a_clean_run():
    rep = run_graph(_g(), MockRunner({"a": {"x": 1}, "b": {"y": 2}}), inputs=GOAL)
    assert rep.passed and rep.failure_kinds == []


def test_the_report_names_every_kind_it_can_distinguish():
    kinds = RunReport(parse_failures=["a: x"], gate_refused="g: y", timeouts=["b: 1s"],
                      assert_failures=["z"], command_failures=["c"], deadlocked=True,
                      budget_exhausted="usd").failure_kinds
    assert kinds == ["parse", "gate", "timeout", "assert", "command", "stall", "budget"]


# ------------------------------------------------------------------ D3-02 / R3-02


class _Slow:
    name = "mock"

    def run(self, node, bb):
        if node["id"] == "a":
            time.sleep(0.5)
        return {"x": 1} if node["id"] == "a" else {"y": 2}


def test_a_node_past_its_declared_deadline_times_out_and_the_run_continues():
    doc = _g()
    doc["nodes"][0]["timeout_s"] = 0.05
    doc["nodes"][0]["retries"] = {"max": 0}
    doc["edges"].append({"from": "a", "to": "b", "kind": "error"})
    rep = run_graph(doc, _Slow(), inputs=GOAL)
    assert rep.timeouts == ["a: 0.05s"]
    assert "timeout" in rep.failure_kinds
    assert "b" in rep.trace, "the error edge must still fire after a timeout"


def test_a_run_wide_default_deadline_applies_to_every_node():
    rep = run_graph(_g(), _Slow(), inputs=GOAL, node_timeout=0.05)
    assert rep.timeouts and rep.timeouts[0].startswith("a: ")
    assert not rep.passed


def test_no_deadline_means_no_thread_and_no_timeout():
    rep = run_graph(_g(), _Slow(), inputs=GOAL)
    assert rep.timeouts == [] and rep.passed


def test_the_schema_accepts_timeout_s_and_validate_reports_it():
    from agenticgraphs.validate import validate_schema

    doc = _g()
    doc["nodes"][0]["timeout_s"] = 30
    assert validate_schema(doc, "graph") == []
    doc["nodes"][0]["timeout_s"] = 0
    assert validate_schema(doc, "graph")
