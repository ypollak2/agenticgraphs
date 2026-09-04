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


# ------------------------------------------------------------------ D2-02 / R3-03


def test_binding_ref_is_resolved_not_decorative():
    """`abilities/run_command.yaml` pointed at a symbol that did not exist and
    nothing read it (D2-02). Now `available()` resolves `binding.ref`."""
    from agenticgraphs import bindings
    from agenticgraphs.registry import iter_yaml
    from agenticgraphs.registry import load as _load

    for path in iter_yaml("abilities"):
        adoc = _load(path)
        if adoc.get("binding"):
            assert bindings.resolve_binding(adoc) is not None, adoc["name"]
    assert bindings.available(allow_mutating=True)["run_command"]["fn"] is bindings.run_command


def test_a_binding_ref_that_does_not_resolve_fails_agr_validate():
    from agenticgraphs.validate import lint_ability

    bad = {"name": "x", "description": "d", "risk": "read",
           "binding": {"kind": "builtin", "ref": "agenticgraphs.bindings:no_such_symbol"}}
    errs = lint_ability(bad)
    assert errs and "does not resolve" in errs[0]
    assert lint_ability({"name": "y", "description": "d"}) == []
    unsupported = {"name": "z", "description": "d",
                   "binding": {"kind": "mcp_tool", "ref": "srv/tool"}}
    assert any("no resolver" in e for e in lint_ability(unsupported))


# ------------------------------------------------------------------ D2-01 / R3-04


def test_an_unbound_world_effect_must_be_declared_narrated():
    from agenticgraphs.validate import lint_graph

    doc = _g()
    doc["nodes"][1] = {"id": "b", "speciality": "release-manager", "abilities": ["cut_release"],
                       "outputs": ["y"]}
    doc["edges"].append({"from": "b", "to": "a", "kind": "compensate"})
    errs = [e for e in lint_graph(doc) if "no binding" in e]
    assert errs and "cut_release" in errs[0] and "unbound_ok" in errs[0]
    doc["nodes"][1]["unbound_ok"] = "narrated: the release is described, not cut, in this runtime"
    assert not [e for e in lint_graph(doc) if "no binding" in e]


def test_board_only_writes_are_not_narration():
    """`generate` is risk: write but writes to the blackboard; producing text is
    what a model does, so it needs no binding and no declaration."""
    from agenticgraphs.validate import lint_graph

    assert not [e for e in lint_graph(_g()) if "no binding" in e]


def test_every_registry_narration_is_on_the_record():
    """38 graphs narrate an unbound effect; each says so per node, and the count
    is a number to burn down, not a silent default."""
    import yaml

    from agenticgraphs.registry import iter_graphs, load

    narrated = [load(g)["name"] for g in iter_graphs()
                if any(n.get("unbound_ok") for n in load(g)["nodes"])]
    assert narrated, "no graph declares unbound_ok — the migration did not run"
    for g in iter_graphs():
        for n in yaml.safe_load(g.read_text())["nodes"]:
            if n.get("unbound_ok"):
                assert n["unbound_ok"].startswith("narrated:"), (g, n["id"])


# ------------------------------------------------------------------ D1-02 / R3-05


def test_retrying_a_non_idempotent_ability_needs_an_explicit_acceptance():
    from agenticgraphs.validate import lint_graph

    doc = _g()
    doc["nodes"][0] = {"id": "a", "speciality": "executor", "abilities": ["execute_step"],
                       "outputs": ["x"], "retries": {"max": 2},
                       "unbound_ok": "narrated: execute_step is the model's account here"}
    errs = [e for e in lint_graph(doc) if "not idempotent" in e]
    assert errs and "execute_step" in errs[0] and "reissue_effects" in errs[0]
    doc["nodes"][0]["retries"]["reissue_effects"] = True
    assert not [e for e in lint_graph(doc) if "not idempotent" in e]


def test_retrying_an_idempotent_ability_needs_nothing():
    from agenticgraphs.validate import lint_graph

    doc = _g()
    doc["nodes"][0]["retries"] = {"max": 2}  # analyze: idempotent by default
    assert not [e for e in lint_graph(doc) if "not idempotent" in e]


def test_the_abilities_that_repeat_their_effect_say_so():
    from agenticgraphs.registry import iter_yaml, load

    flagged = {load(p)["name"] for p in iter_yaml("abilities") if load(p).get("idempotent") is False}
    assert {"run_command", "edit_files", "execute_step", "file_record", "cut_release",
            "shadow_write", "backfill", "escalate", "approve"} <= flagged


# ------------------------------------------------------------------ D6-01 / R3-06


def _triage(verify_inputs=None, expected_from_verify=True):
    doc = _g(
        nodes=[{"id": "route", "speciality": "producer", "abilities": ["generate"],
                "outputs": ["assigned"]},
               {"id": "verify", "speciality": "critic", "abilities": ["critique"], "kind": "verifier",
                "criteria": "the route agrees with the policy table the caller supplied",
                "outputs": (["expected"] if expected_from_verify else []) + ["assigned", "output"],
                **({"inputs": verify_inputs} if verify_inputs else {})}],
        edges=[{"from": "route", "to": "verify"}],
        verification=[{"assert": "output.assigned == output.expected"}],
        state={"inputs": ["goal", "policy_table"]},
    )
    if not expected_from_verify:
        # A separate node establishes the reference; the measured side comes
        # from `route`. Neither node holds both sides, so nobody grades itself.
        doc["nodes"].insert(1, {"id": "lookup", "speciality": "analyst", "abilities": ["analyze"],
                                "outputs": ["expected"]})
        doc["edges"] = [{"from": "route", "to": "lookup"}, {"from": "lookup", "to": "verify"}]
    return doc


def _sg(doc):
    from agenticgraphs.validate import lint_graph

    return [e for e in lint_graph(doc) if "self-graded" in e]


def test_a_reworded_comparison_whose_reference_the_verifier_invents_is_refused():
    errs = _sg(_triage())
    assert errs and "expected" in errs[0] and "verify" in errs[0]


def test_declaring_the_callers_reference_as_an_input_anchors_the_verifier():
    assert _sg(_triage(verify_inputs=["policy_table"])) == []


def test_a_reference_produced_upstream_is_not_self_graded():
    assert _sg(_triage(expected_from_verify=False)) == []


def test_a_comparison_against_a_literal_is_weak_but_not_circular():
    doc = _triage()
    doc["verification"] = [{"assert": "len(output.assigned) > 0"}]
    assert _sg(doc) == []


def test_the_sixteen_evaded_graphs_now_read_an_external_reference():
    """The stale report listed 16; the provenance rule recovered exactly those,
    and each was fixed structurally rather than reworded."""
    from agenticgraphs.registry import iter_graphs, load

    for gp in iter_graphs():
        assert _sg(load(gp)) == [], gp


def test_a_node_cannot_overwrite_what_the_caller_supplied():
    doc = _g(state={"inputs": ["goal", "threshold"]})
    doc["nodes"][0]["inputs"] = ["threshold"]
    doc["verification"] = [{"assert": "output.x >= output.threshold"}]
    rep = run_graph(doc, MockRunner({"a": {"x": 5, "threshold": 1}, "b": {"y": 2}}),
                    inputs={**GOAL, "threshold": 10})
    assert rep.overwritten_inputs == ["a: tried to overwrite caller input 'threshold'"]
    assert not rep.passed, "the model's own threshold must not be the bar it is measured against"
