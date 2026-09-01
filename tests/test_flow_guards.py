"""An edge guarded on a key nothing produces is a dead edge, and it fails silently.

`edge_true` catches every exception and returns False. That is right at run time —
an unresolvable condition means the edge is not taken — and catastrophic at
authoring time: the retry never retries, the compensator never compensates, and
every golden case still passes because the fixture supplied the key by hand. Only
a live run reaches the guard with a blackboard a model wrote, which is why 52 dead
guards across 43 graphs survived until the first v1.8 recording sweep.

v1.7 found this for `attempts` and fixed that one name. These tests pin the
general rule.
"""
from __future__ import annotations

import pytest
import yaml

from agenticgraphs.harness import MockRunner, run_graph
from agenticgraphs.registry import iter_graphs, load
from agenticgraphs.validate import _lint_flow_keys


def test_no_graph_is_guarded_on_a_key_nothing_produces():
    for gpath in iter_graphs():
        doc = load(gpath)
        assert _lint_flow_keys(doc) == [], doc["name"]


def test_a_dead_guard_is_refused():
    doc = {"apiVersion": "agr/v1.8", "state": {"inputs": []},
           "nodes": [{"id": "a", "outputs": ["x"]}, {"id": "b", "outputs": ["y"]}],
           "edges": [{"from": "a", "to": "b", "when": "verify_failed and attempts < 3"}]}
    assert _lint_flow_keys(doc)
    doc["nodes"][0]["outputs"] = ["x", {"verify_failed": "bool"}]
    assert _lint_flow_keys(doc) == [], "declaring it must clear the finding"


def test_attempts_is_owned_by_the_runtime_not_by_a_node():
    """v1.7 published it from `run_graph`; a guard may read it with nothing
    declaring it, and requiring a declaration would break 48 guards."""
    doc = {"apiVersion": "agr/v1.8", "nodes": [{"id": "a", "outputs": ["x"]},
                                               {"id": "b", "outputs": ["y"]}],
           "edges": [{"from": "a", "to": "b", "when": "attempts < 3"}]}
    assert _lint_flow_keys(doc) == []


def test_an_approval_contract_is_checked_too():
    doc = {"apiVersion": "agr/v1.8",
           "nodes": [{"id": "a", "outputs": ["x"]},
                     {"id": "gate", "kind": "human", "outputs": ["signed_off"],
                      "approval": {"contract": "signed_off == true and reconciled == true"}}],
           "edges": [{"from": "a", "to": "gate"}]}
    assert _lint_flow_keys(doc), "an approval gate on an undeclared key can never pass"


def test_the_rule_is_armed_at_v1_8_only():
    doc = {"apiVersion": "agr/v1.7", "nodes": [{"id": "a"}, {"id": "b"}],
           "edges": [{"from": "a", "to": "b", "when": "nope"}]}
    assert _lint_flow_keys(doc) == []


# ----------------------------------------------------- the loops actually fire

@pytest.mark.parametrize("name,loop_node,fail_key", [
    ("verifier-swarm", "worker", "verify_failed"),
    ("meeting-to-actions", "produce", "revision_requested"),
    ("bug-triage-and-fix", "execute", "verify_failed"),
])
def test_a_retry_loop_runs_twice_when_the_guard_says_so(name, loop_node, fail_key):
    """The behaviour the declaration buys. Before it, this ran the node once and
    the bounded retry the contract advertises never happened."""
    doc = load(next(g for g in iter_graphs() if load(g)["name"] == name))
    cases = yaml.safe_load(
        (next(g for g in iter_graphs() if load(g)["name"] == name).parent / "cases.yaml").read_text()
    )["cases"]
    outs = {k: dict(v) if isinstance(v, dict) else v
            for k, v in cases[0]["node_outputs"].items()}
    # The node whose outcome the guard describes reports failure once, then success.
    src = next(e["from"] for e in doc["edges"]
               if e.get("when") and fail_key in e["when"] and e["to"] == loop_node)
    base = outs.get(src) or {}
    outs[src] = [{**base, fail_key: True}, {**base, fail_key: False}]
    rep = run_graph(doc, MockRunner(outs), inputs={"goal": "g", **(cases[0].get("inputs") or {})})
    assert rep.trace.count(loop_node) == 2, (
        f"{name}: guard on {fail_key} did not re-enter {loop_node} — trace {rep.trace}"
    )


# ------------------------------------------------- a run that stops short says so

def test_a_run_that_reaches_no_terminal_reports_it():
    """Three graphs in the first v1.8 sweep failed with `AttributeError: <key>`.

    That reads like a model formatting problem. The truth was that `post`, `enrol`
    and `offer` never executed — the workflow stopped mid-way and the contract was
    reporting the symptom. `passed` was already False; the diagnosis was wrong.
    """
    doc = yaml.safe_load("""
apiVersion: agr/v1.8
name: stops-short
description: a graph used only by unit tests
category: software-engineering
state: {inputs: [goal]}
goal: {required: true, description: the subject}
nodes:
- {id: a, speciality: producer, abilities: [generate], outputs: [{go: bool}]}
- {id: b, speciality: producer, abilities: [generate], outputs: [x]}
- {id: end, speciality: critic, abilities: [critique], kind: verifier, outputs: [x, output],
   criteria: the run reached the end rather than stopping at a branch nobody took}
edges:
- {from: a, to: b, when: go}
- {from: b, to: end}
termination: {max_steps: 6, contract: the run completes}
verification: [{assert: "output.x"}]
""")
    rep = run_graph(doc, MockRunner({"a": {"go": False}}), inputs={"goal": "g"})
    assert rep.unreached_terminals == ["end"]
    assert not rep.passed
    rep2 = run_graph(doc, MockRunner({"a": {"go": True}, "b": {"x": 1},
                                      "end": {"x": 1, "output": {"x": 1}}}),
                     inputs={"goal": "g"})
    assert rep2.unreached_terminals == [] and rep2.passed


def test_a_recovery_terminal_not_running_is_the_desired_outcome():
    """A clean run must not be failed for skipping its compensator. Both failure
    edge kinds count: `_normalize` desugars `on_error` into an `error` edge, so a
    compensator usually has one of each and testing `compensate` alone misses it."""
    from agenticgraphs.registry import ROOT

    doc = load(next(g for g in iter_graphs()
                    if load(g)["name"] == "feature-delivery-lifecycle"))
    cases = yaml.safe_load(
        (next(g for g in iter_graphs()
              if load(g)["name"] == "feature-delivery-lifecycle").parent / "cases.yaml").read_text()
    )["cases"]
    clean = next(c for c in cases if c["id"] == "clean-path-releases")
    rep = run_graph(doc, MockRunner(clean["node_outputs"]), root=ROOT,
                    inputs={"goal": "g", **(clean.get("inputs") or {})})
    assert "rollback" not in rep.trace
    assert rep.unreached_terminals == [], "a clean run was failed for not rolling back"


def test_every_registry_graph_reaches_a_terminal_on_its_golden_cases():
    from agenticgraphs.evalcmd import case_inputs
    from agenticgraphs.registry import ROOT, cases_path

    for gpath in iter_graphs():
        doc = load(gpath)
        for case in yaml.safe_load(cases_path(doc["name"]).read_text())["cases"]:
            rep = run_graph(doc, MockRunner(case["node_outputs"]), root=ROOT,
                            inputs=case_inputs(case))
            assert rep.unreached_terminals == [], f"{doc['name']}/{case['id']}"


# ------------------------------------------- a bounded retry must have an exit

def test_no_graph_stalls_when_its_retry_bound_is_reached():
    from agenticgraphs.validate import _lint_stall

    for gpath in iter_graphs():
        assert _lint_stall(load(gpath)) == [], load(gpath)["name"]


def test_the_uncovered_case_is_the_bound_being_reached():
    """Retry while failing with attempts left, advance when it worked — and
    nothing for still-failing-and-out-of-attempts. The run stops there: not
    failed, not escalated, just stopped."""
    from agenticgraphs.validate import _lint_stall

    doc = {"apiVersion": "agr/v1.8",
           "nodes": [{"id": "work"}, {"id": "check"}, {"id": "ship"}],
           "edges": [{"from": "work", "to": "check"},
                     {"from": "check", "to": "work", "when": "failed and attempts < 3"},
                     {"from": "check", "to": "ship", "when": "not failed"}]}
    assert _lint_stall(doc)
    doc["nodes"].append({"id": "escalate"})
    doc["edges"].append({"from": "check", "to": "escalate",
                         "when": "failed and attempts >= 3"})
    assert _lint_stall(doc) == []


def test_a_lone_success_path_cannot_express_failure():
    """`rights-check -> publish when rights_clear` was the whole forward flow, so
    unclear rights looked identical to rights being clear."""
    from agenticgraphs.validate import _lint_stall

    doc = {"apiVersion": "agr/v1.8",
           "nodes": [{"id": "check"}, {"id": "publish"}],
           "edges": [{"from": "check", "to": "publish", "when": "clear"}]}
    assert _lint_stall(doc)


def test_a_terminal_that_loops_is_not_a_stall():
    """A node whose only edge is a retry back-edge IS the end of the graph.
    Counting those turned 11 real findings into 51."""
    from agenticgraphs.validate import _lint_stall

    doc = {"apiVersion": "agr/v1.8",
           "nodes": [{"id": "produce"}, {"id": "review"}],
           "edges": [{"from": "produce", "to": "review"},
                     {"from": "review", "to": "produce",
                      "when": "revision_requested and attempts < 2"}]}
    assert _lint_stall(doc) == []


def test_an_exhausted_retry_now_reaches_an_escalation_terminal():
    """The behaviour the escalation edge buys, on a real graph.

    `regulatory-filing-lifecycle` reconciled three times against figures it could
    not balance and then stopped — the filing neither made nor formally abandoned.
    """
    from agenticgraphs.evalcmd import case_inputs
    from agenticgraphs.registry import ROOT, cases_path

    doc = load(next(g for g in iter_graphs()
                    if load(g)["name"] == "regulatory-filing-lifecycle"))
    case = yaml.safe_load(cases_path("regulatory-filing-lifecycle").read_text())["cases"][0]
    outs = {k: (dict(v) if isinstance(v, dict) else v)
            for k, v in case["node_outputs"].items()}
    outs["reconcile"] = [{"reconciled": False}] * 4   # never reconciles
    rep = run_graph(doc, MockRunner(outs), root=ROOT, inputs=case_inputs(case))
    assert "abandon-filing" in rep.trace, (
        f"an unreconcilable filing stalled instead of being abandoned: {rep.trace}"
    )
    assert rep.unreached_terminals == [], "the run reached a terminal"


def test_a_refused_approval_is_not_reported_as_a_stall():
    """The gate saying no is an answer, not a missing edge.

    `vuln-remediation-lifecycle` reached `disclose-approval`, which refused to sign
    because the recorded exit codes did not show the exploit blocked. The run
    correctly stopped. Calling that "stopped short" sends a reader looking for a
    topology bug when a check simply said no.
    """
    from agenticgraphs.evalcmd import case_inputs
    from agenticgraphs.registry import ROOT, cases_path

    doc = load(next(g for g in iter_graphs()
                    if load(g)["name"] == "vuln-remediation-lifecycle"))
    case = yaml.safe_load(cases_path("vuln-remediation-lifecycle").read_text())["cases"][0]
    outs = {k: (dict(v) if isinstance(v, dict) else v)
            for k, v in case["node_outputs"].items()}
    # Reaches the gate (`exploit_blocked` routes it there) carrying evidence that
    # does not support disclosure: the PoC still succeeds after the patch, so the
    # approval contract on those exit codes cannot hold.
    outs["prove"] = {"exploit_blocked": True,
                     "repro_exit_code_before": 0, "repro_exit_code_after": 0}
    rep = run_graph(doc, MockRunner(outs), root=ROOT, auto_approve=True,
                    inputs=case_inputs(case))
    assert any(not ok for _, ok in rep.approvals), "the gate should have refused"
    assert rep.unreached_terminals == [], (
        "a refused approval was reported as a stall"
    )
