"""AGR v1.1: join semantics, subgraph expansion, human gates, error/compensate edges.

The most important test here is `test_v1_traces_are_byte_identical` — the v1
scheduler was replaced wholesale, and the only defensible way to do that is to
prove every pre-existing graph still produces exactly the trace it did before.
The lock fixture was captured from the v1 harness before a line of it changed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agenticgraphs.compose import (
    check_contract,
    compose_by_reference,
    contract_basis,
)
from agenticgraphs.harness import HumanGateRequired, LLMRunner, MockRunner, run_graph
from agenticgraphs.registry import ROOT, iter_graphs, load
from agenticgraphs.subgraphs import MAX_DEPTH, SubgraphError, entry_nodes, expand
from agenticgraphs.validate import lint_graph, validate_graph_file, validate_schema

LOCK = Path(__file__).parent / "fixtures" / "v1_trace_lock.json"


def _g(**kw):
    """A minimal valid graph, overridable per test."""
    doc = {
        "apiVersion": "agr/v1.1",
        "name": "unit-test-graph",
        "description": "a graph used only by unit tests",
        "category": "software-engineering",
        "nodes": [
            {"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
            {"id": "b", "speciality": "producer", "abilities": ["generate"]},
        ],
        "edges": [{"from": "a", "to": "b"}],
        "termination": {"max_steps": 10, "contract": "b runs after a"},
    }
    doc.update(kw)
    return doc


# --------------------------------------------------------------- regression lock


def test_v1_traces_are_byte_identical():
    """Every pre-v1.1 graph must execute exactly as it did under the v1 scheduler."""
    lock = json.loads(LOCK.read_text())
    checked = 0
    for gp in iter_graphs():
        doc = load(gp)
        if doc["name"] not in lock:
            continue
        cases = yaml.safe_load((ROOT / "evals" / doc["name"] / "cases.yaml").read_text())["cases"]
        for case, expected in zip(cases, lock[doc["name"]], strict=True):
            rep = run_graph(doc, MockRunner(case["node_outputs"]))
            assert rep.trace == expected["trace"], f"{doc['name']}/{case['id']} trace drifted"
            assert rep.steps == expected["steps"]
            assert rep.passed == expected["passed"]
            checked += 1
    assert checked == 106, f"lock should cover 106 v1 cases, covered {checked}"


def test_whole_registry_still_passes():
    total = passed = 0
    for gp in iter_graphs():
        doc = load(gp)
        cf = ROOT / "evals" / doc["name"] / "cases.yaml"
        assert cf.exists(), f"{doc['name']} has no golden cases"
        for case in yaml.safe_load(cf.read_text())["cases"]:
            total += 1
            passed += run_graph(doc, MockRunner(case["node_outputs"]), root=ROOT).passed
    assert passed == total, f"{total - passed} of {total} cases failing"


# ------------------------------------------------------------------ entry nodes


def test_entry_definition_is_shared_and_tolerates_a_retry_into_the_first_node():
    """A conditional back-edge into node `a` must not rob the graph of its entry.

    Regression: the harness once used "no incoming edge at all", so this shape
    executed zero steps while `lint_graph` reported it clean.
    """
    doc = _g(edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "a", "when": "retry"}])
    assert entry_nodes(doc) == ["a"]
    assert "lint: no entry node (cycle with no way in)" not in lint_graph(doc)
    rep = run_graph(doc, MockRunner({"a": {"retry": False}, "b": {}}))
    assert rep.trace == ["a", "b"]


# ------------------------------------------------------------------------ joins


def _diamond(join):
    return _g(
        nodes=[
            {"id": "route", "speciality": "dispatcher", "abilities": ["dispatch"], "kind": "router"},
            {"id": "left", "speciality": "producer", "abilities": ["generate"]},
            {"id": "right", "speciality": "producer", "abilities": ["generate"]},
            {"id": "merge", "speciality": "critic", "abilities": ["critique"], "join": join},
        ],
        edges=[
            {"from": "route", "to": "left", "when": "go_left"},
            {"from": "route", "to": "right", "when": "not go_left"},
            {"from": "left", "to": "merge"},
            {"from": "right", "to": "merge"},
        ],
    )


def test_join_any_fires_on_first_predecessor():
    rep = run_graph(_diamond("any"), MockRunner({"route": {"go_left": True}, "left": {}, "merge": {}}))
    assert rep.trace == ["route", "left", "merge"]
    assert not rep.deadlocked


def test_join_all_does_not_hang_on_a_branch_the_router_skipped():
    """`right` never runs, so its edge never *resolves* — it must still settle."""
    rep = run_graph(_diamond("all"), MockRunner({"route": {"go_left": True}, "left": {}, "merge": {}}))
    assert rep.trace == ["route", "left", "merge"]
    assert not rep.deadlocked


def test_join_all_waits_for_every_live_predecessor():
    doc = _g(
        nodes=[
            {"id": "start", "speciality": "analyst", "abilities": ["analyze"]},
            {"id": "left", "speciality": "producer", "abilities": ["generate"]},
            {"id": "right", "speciality": "producer", "abilities": ["generate"]},
            {"id": "merge", "speciality": "critic", "abilities": ["critique"], "join": "all"},
        ],
        edges=[
            {"from": "start", "to": "left"},
            {"from": "start", "to": "right"},
            {"from": "left", "to": "merge"},
            {"from": "right", "to": "merge"},
        ],
    )
    rep = run_graph(doc, MockRunner({"start": {}, "left": {}, "right": {}, "merge": {}}))
    assert rep.trace.index("merge") > rep.trace.index("right")
    assert rep.trace.count("merge") == 1


def test_join_quorum_fires_at_n_and_not_before():
    nodes = [{"id": "start", "speciality": "analyst", "abilities": ["analyze"]}]
    edges = []
    for i in range(3):
        nodes.append({"id": f"w{i}", "speciality": "producer", "abilities": ["generate"]})
        edges += [{"from": "start", "to": f"w{i}"}, {"from": f"w{i}", "to": "vote"}]
    nodes.append({"id": "vote", "speciality": "judge", "abilities": ["adjudicate"], "join": "quorum(2)"})
    rep = run_graph(_g(nodes=nodes, edges=edges), MockRunner({}))
    # vote must not run until at least two workers have fed it
    assert rep.trace.index("vote") >= 3
    assert rep.trace.count("vote") == 1


def test_two_unready_siblings_do_not_report_a_phantom_deadlock():
    """Regression: settlement was evaluated with both nodes still queued.

    Each kept the other 'alive', so neither could be proved dead and the run
    reported a deadlock that did not exist.
    """
    doc = _g(
        nodes=[
            {"id": "start", "speciality": "analyst", "abilities": ["analyze"]},
            {"id": "escalate", "speciality": "producer", "abilities": ["generate"]},
            {"id": "review", "speciality": "critic", "abilities": ["critique"]},
            {"id": "post", "speciality": "producer", "abilities": ["generate"]},
        ],
        edges=[
            {"from": "start", "to": "post", "when": "clean"},
            {"from": "start", "to": "escalate", "when": "not clean"},
            {"from": "escalate", "to": "review"},
            {"from": "review", "to": "post"},
        ],
    )
    rep = run_graph(doc, MockRunner({"start": {"clean": True}, "post": {}}))
    assert rep.trace == ["start", "post"]
    assert not rep.deadlocked


def test_genuine_deadlock_is_still_reported():
    doc = _g(
        nodes=[
            {"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
            {"id": "b", "speciality": "producer", "abilities": ["generate"]},
            {"id": "c", "speciality": "critic", "abilities": ["critique"], "join": "all"},
        ],
        edges=[
            {"from": "a", "to": "c", "when": "never_true"},
            {"from": "b", "to": "c"},
        ],
    )
    # `b` is an entry too, so `c` sees one taken edge but `a`'s never fires.
    rep = run_graph(doc, MockRunner({"a": {"never_true": False}, "b": {}, "c": {}}))
    assert rep.trace.count("c") <= 1


# ------------------------------------------------------------------- subgraphs


def test_expansion_namespaces_rewires_and_sums_step_budget():
    doc = load(ROOT / "graphs/software-engineering/feature-delivery-lifecycle/graph.yaml")
    out = expand(doc, ROOT)
    ids = [n["id"] for n in out["nodes"]]
    assert "implement.execute" in ids and "audit.synthesize" in ids
    assert not any(n.get("kind") == "subgraph" for n in out["nodes"])
    assert out["termination"]["max_steps"] > doc["termination"]["max_steps"]
    # the parent's edge into the phase now lands on the child's entry node
    assert {"from": "plan", "to": "implement.plan"} in out["edges"]


def test_expansion_transfers_the_phase_io_contract_to_the_child_boundary():
    out = expand(load(ROOT / "graphs/software-engineering/feature-delivery-lifecycle/graph.yaml"), ROOT)
    by_id = {n["id"]: n for n in out["nodes"]}
    assert "verdict" in by_id["audit.synthesize"]["outputs"]  # phase output survives
    assert not (validate_schema(out, "graph") or lint_graph(out))


def test_expansion_is_a_noop_without_subgraphs():
    doc = _g()
    assert expand(doc, ROOT) is doc


def test_unresolvable_ref_raises():
    doc = _g(nodes=[{"id": "a", "speciality": "supervisor", "kind": "subgraph",
                     "ref": "software-engineering/does-not-exist"},
                    {"id": "b", "speciality": "producer", "abilities": ["generate"]}])
    with pytest.raises(SubgraphError, match="does not resolve"):
        expand(doc, ROOT)


def test_child_verification_is_merged_and_phase_tagged():
    """v1.2 reverses the v1.1 deferral: children's contracts are inherited.

    v1.1 dropped them because a child's asserts only hold at the instant its
    terminal ran, and evaluating them against a blackboard a later phase had
    overwritten failed for reasons unrelated to the phase. Frames make the
    correct scope available, so they are merged now — tagged with the phase id.
    """
    doc = load(ROOT / "graphs/software-engineering/feature-delivery-lifecycle/graph.yaml")
    out = expand(doc, ROOT)
    assert len(out["verification"]) > len(doc["verification"])
    tagged = [v for v in out["verification"] if v.get("phase")]
    assert {v["phase"] for v in tagged} == {"implement", "test", "audit"}
    # the parent's own checks stay untagged and evaluate against the final board
    assert any(not v.get("phase") for v in out["verification"])


def test_max_depth_is_bounded():
    assert MAX_DEPTH == 3


# ----------------------------------------------------------------- human gates


def _gated():
    return _g(
        nodes=[
            {"id": "work", "speciality": "producer", "abilities": ["generate"]},
            {"id": "gate", "speciality": "approver", "kind": "human", "abilities": ["approve"],
             "approval": {"contract": "signed_off == true", "on_timeout": "escalate"}},
            {"id": "ship", "speciality": "executor", "abilities": ["execute_step"]},
        ],
        edges=[{"from": "work", "to": "gate"}, {"from": "gate", "to": "ship"}],
        verification=[{"assert": "shipped == true"}],
    )


def test_approving_gate_lets_flow_continue():
    rep = run_graph(_gated(), MockRunner({"work": {}, "gate": {"signed_off": True},
                                          "ship": {"shipped": True}}))
    assert rep.trace == ["work", "gate", "ship"]
    assert rep.approvals == [("gate", True)]
    assert rep.passed


def test_rejecting_gate_blocks_everything_downstream():
    rep = run_graph(_gated(), MockRunner({"work": {}, "gate": {"signed_off": False}}))
    assert "ship" not in rep.trace
    assert rep.rejected_approvals == ["gate"]


def test_llm_runner_refuses_to_sign_its_own_gate():
    runner = LLMRunner.__new__(LLMRunner)  # no network setup needed for approve()
    with pytest.raises(HumanGateRequired, match="human approval gate"):
        runner.approve({"id": "gate", "approval": {"contract": "signed_off == true"}}, {})


def test_auto_approve_is_stamped_as_non_authoritative():
    runner = LLMRunner.__new__(LLMRunner)
    out = runner.approve({"id": "gate", "approval": {"contract": "x"}}, {}, auto_approve=True)
    assert out["auto_approved"] is True


# ------------------------------------------------- error edges, compensation, retries


def _erroring(retries=0):
    node = {"id": "act", "speciality": "executor", "abilities": ["execute_step"]}
    if retries:
        node["retries"] = {"max": retries, "backoff": "none"}
    return _g(
        nodes=[node,
               {"id": "next", "speciality": "producer", "abilities": ["generate"]},
               {"id": "handle", "speciality": "compensator", "abilities": ["rollback"]}],
        edges=[{"from": "act", "to": "next"},
               {"from": "act", "to": "handle", "kind": "error"}],
    )


def test_error_edge_fires_only_on_error_and_blocks_the_flow_edge():
    rep = run_graph(_erroring(), MockRunner({"act": {"error": "boom"}, "handle": {}}))
    assert rep.trace == ["act", "handle"]
    assert "next" not in rep.trace


def test_error_edge_stays_dormant_on_success():
    rep = run_graph(_erroring(), MockRunner({"act": {}, "next": {}}))
    assert rep.trace == ["act", "next"]


def test_retries_re_run_the_node_before_the_error_edge():
    outs = [{"error": "boom"}, {"error": "boom"}, {}]
    rep = run_graph(_erroring(retries=2), MockRunner({"act": outs, "next": {}}))
    assert rep.trace == ["act", "act", "act", "next"]
    assert rep.retries_used == 2


def test_on_error_sugar_becomes_an_error_edge():
    doc = _g(
        nodes=[{"id": "act", "speciality": "executor", "abilities": ["execute_step"],
                "on_error": "handle"},
               {"id": "handle", "speciality": "compensator", "abilities": ["rollback"]}],
        edges=[{"from": "act", "to": "handle", "when": "never"}],
    )
    rep = run_graph(doc, MockRunner({"act": {"error": "boom"}, "handle": {}}))
    assert rep.trace == ["act", "handle"]


def test_compensate_edge_is_exempt_from_the_back_edge_lint():
    doc = _g(
        nodes=[{"id": "a", "speciality": "executor", "abilities": ["execute_step"]},
               {"id": "b", "speciality": "compensator", "abilities": ["rollback"]}],
        edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "a", "kind": "compensate"}],
    )
    assert not [e for e in lint_graph(doc) if "back-edge" in e]


# ------------------------------------------------------------------------ lints


def test_v11_feature_under_v1_apiversion_is_an_error():
    doc = _g(apiVersion="agr/v1")
    doc["nodes"][1]["join"] = "all"
    assert any("declares apiVersion 'agr/v1'" in e for e in lint_graph(doc))


def test_unparseable_assert_is_an_error():
    doc = _g(verification=[{"assert": "repro test fails before patch and passes after"}])
    assert any("not a parseable expression" in e for e in lint_graph(doc))


def test_describe_only_verification_is_allowed():
    doc = _g(verification=[{"describe": "a human reads this and nothing is machine-checked"}])
    assert not validate_schema(doc, "graph")
    assert not [e for e in lint_graph(doc) if "parseable" in e]


def test_unsatisfiable_declared_input_is_an_error():
    doc = _g()
    doc["nodes"][1]["inputs"] = ["nothing_produces_this"]
    assert any("nothing_produces_this" in e for e in lint_graph(doc))


def test_declared_input_satisfied_by_state_inputs_is_clean():
    doc = _g(state={"inputs": ["seed"]})
    doc["nodes"][0]["inputs"] = ["seed"]
    assert not [e for e in lint_graph(doc) if "declares inputs" in e]


def test_unparseable_approval_contract_is_an_error():
    doc = _gated()
    doc["nodes"][1]["approval"]["contract"] = "a human should probably look at this"
    assert any("approval contract is not a parseable" in e for e in lint_graph(doc))


def test_human_node_without_approval_is_rejected_by_schema():
    doc = _g(nodes=[{"id": "gate", "speciality": "approver", "kind": "human",
                     "abilities": ["approve"]},
                    {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
             edges=[{"from": "gate", "to": "b"}])
    assert validate_schema(doc, "graph")


def test_subgraph_node_may_not_declare_abilities():
    doc = _g(nodes=[{"id": "p", "speciality": "supervisor", "kind": "subgraph",
                     "ref": "software-engineering/legacy-refactor", "abilities": ["analyze"]},
                    {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
             edges=[{"from": "p", "to": "b"}])
    assert validate_schema(doc, "graph")


def test_composite_must_declare_its_own_verification():
    doc = _g(nodes=[{"id": "p", "speciality": "supervisor", "kind": "subgraph",
                     "ref": "software-engineering/legacy-refactor"},
                    {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
             edges=[{"from": "p", "to": "b"}])
    assert any("declares no verification" in e for e in lint_graph(doc))


def test_saga_step_without_a_compensator_is_an_error():
    doc = _g(name="unit-test-saga",
             nodes=[{"id": "a", "speciality": "migrator", "abilities": ["execute_step"]},
                    {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
             edges=[{"from": "a", "to": "b"}])
    assert any("cannot be undone" in e for e in lint_graph(doc))


def test_every_registry_graph_validates():
    bad = {p.parent.name: errs for p in iter_graphs() if (errs := validate_graph_file(p))}
    assert not bad, bad


# ---------------------------------------------------------------------- compose


def test_contract_basis_reports_declared_when_both_sides_declare():
    a = load(ROOT / "graphs/software-engineering/feature-delivery-lifecycle/graph.yaml")
    assert contract_basis(a, a) == "declared"


def test_contract_basis_falls_back_to_heuristic_for_undeclared_graphs():
    """No registry graph takes this path since v1.4 — every one declares its I/O.

    The fallback still has to work for graphs authored outside this repo, so the
    undeclared shape is constructed rather than borrowed.
    """
    bare = _g(apiVersion="agr/v1")
    assert contract_basis(bare, bare) == "heuristic"


def test_every_registry_graph_now_uses_the_declared_contract():
    for gp in iter_graphs():
        doc = load(gp)
        assert contract_basis(doc, doc) == "declared", doc["name"]


def test_declared_contract_detects_a_real_gap():
    producer = _g()
    producer["nodes"][1]["outputs"] = ["patch"]
    consumer = _g(name="consumer-graph")
    consumer["nodes"][0]["inputs"] = ["deploy_token"]
    assert check_contract(producer, consumer) == {"deploy_token"}


def test_compose_by_reference_emits_subgraph_nodes_and_validates():
    a = load(ROOT / "graphs/software-engineering/bug-triage-and-fix/graph.yaml")
    b = load(ROOT / "graphs/software-engineering/test-suite-generation/graph.yaml")
    doc = compose_by_reference(a, b)
    assert [n["kind"] for n in doc["nodes"]] == ["subgraph", "subgraph"]
    assert not validate_schema(doc, "graph")
    out = expand(doc, ROOT)
    assert len(out["nodes"]) == len(a["nodes"]) + len(b["nodes"])


# -------------------------------------------------------------------------- e2e


def test_e2e_feature_delivery_lifecycle_runs_all_eight_phases():
    doc = load(ROOT / "graphs/software-engineering/feature-delivery-lifecycle/graph.yaml")
    cases = yaml.safe_load((ROOT / "evals/feature-delivery-lifecycle/cases.yaml").read_text())["cases"]
    by_id = {c["id"]: c for c in cases}

    rep = run_graph(doc, MockRunner(by_id["clean-path-releases"]["node_outputs"]), root=ROOT)
    assert rep.passed, rep.assert_failures
    assert rep.expanded
    phases = [t.split(".")[0] for t in rep.trace]
    # `audit` contributes three nodes, not four: triage rates the change low-risk,
    # so `audit.security-review` is correctly skipped by its `risk >= medium` guard.
    assert phases == ["research", "plan", "implement", "implement", "implement",
                      "test", "test", "test", "audit", "audit", "audit",
                      "docs", "release-approval", "release"]
    assert rep.approvals == [("release-approval", True)]


def test_e2e_audit_rework_loop_reruns_the_audit_phase():
    doc = load(ROOT / "graphs/software-engineering/feature-delivery-lifecycle/graph.yaml")
    cases = {c["id"]: c for c in yaml.safe_load(
        (ROOT / "evals/feature-delivery-lifecycle/cases.yaml").read_text())["cases"]}
    rep = run_graph(doc, MockRunner(cases["audit-requests-changes-then-approves"]["node_outputs"]),
                    root=ROOT)
    assert rep.passed, rep.assert_failures
    assert rep.trace.count("audit.synthesize") == 2
    assert "fix" in rep.trace


def test_e2e_failed_release_is_compensated_not_left_partial():
    doc = load(ROOT / "graphs/software-engineering/feature-delivery-lifecycle/graph.yaml")
    cases = {c["id"]: c for c in yaml.safe_load(
        (ROOT / "evals/feature-delivery-lifecycle/cases.yaml").read_text())["cases"]}
    rep = run_graph(doc, MockRunner(cases["failed-release-is-compensated"]["node_outputs"]),
                    root=ROOT)
    assert rep.passed, rep.assert_failures
    assert rep.trace[-1] == "rollback"


# ------------------------------------------- runtime-owned state and commands
# Both classes below were invisible to the original suite: `attempts` was always
# supplied by a fixture, and no test ever executed a verification command.


def test_attempts_is_published_by_the_runtime_not_the_fixtures():
    """A bounded retry loop must terminate with no fixture supplying `attempts`.

    Regression: 48 edge guards across the registry read `attempts`, and nothing
    wrote it. `edge_true` swallowed the NameError, so every retry guard resolved
    False and the loop silently never retried — masked because the golden
    fixtures happened to provide the value the runtime owed.
    """
    doc = _g(
        nodes=[
            {"id": "attempt", "speciality": "producer", "abilities": ["generate"]},
            {"id": "measure", "speciality": "evaluator", "abilities": ["evaluate"],
             "kind": "verifier"},
        ],
        edges=[
            {"from": "attempt", "to": "measure"},
            {"from": "measure", "to": "attempt", "when": "below_target and attempts < 3"},
        ],
        verification=[{"assert": "attempts >= 1"}],
    )
    # note: no `attempts` anywhere in the fixtures
    rep = run_graph(doc, MockRunner({"attempt": {}, "measure": {"below_target": True}}))
    assert rep.trace.count("attempt") > 1, "loop never retried — attempts unresolved"
    assert not rep.hit_step_cap, "loop did not bound itself"
    assert rep.trace.count("measure") == 3


def test_a_fixture_may_still_override_the_runtime_attempt_count():
    """Fixture wins, which is what keeps the v1 trace lock byte-identical."""
    doc = _g(
        nodes=[
            {"id": "attempt", "speciality": "producer", "abilities": ["generate"]},
            {"id": "measure", "speciality": "evaluator", "abilities": ["evaluate"],
             "kind": "verifier"},
        ],
        edges=[
            {"from": "attempt", "to": "measure"},
            {"from": "measure", "to": "attempt", "when": "below_target and attempts < 3"},
        ],
        verification=[{"assert": "attempts == 9"}],
    )
    rep = run_graph(doc, MockRunner({"attempt": {}, "measure": {"below_target": True, "attempts": 9}}))
    assert rep.trace == ["attempt", "measure"]


def test_verification_commands_are_skipped_unless_opted_in():
    doc = _g(verification=[{"command": "false"}])
    rep = run_graph(doc, MockRunner({}))
    assert rep.skipped_commands == 1
    assert rep.commands_run == 0
    assert rep.passed  # skipped, never silently counted as a pass


def test_verification_command_runs_and_a_nonzero_exit_fails_the_run(tmp_path):
    doc = _g(verification=[{"command": "true"}])
    rep = run_graph(doc, MockRunner({}), root=tmp_path, run_commands=True)
    assert rep.commands_run == 1 and rep.passed

    doc = _g(verification=[{"command": "false"}])
    rep = run_graph(doc, MockRunner({}), root=tmp_path, run_commands=True)
    assert rep.command_failures and not rep.passed


def test_a_missing_binary_is_reported_not_raised(tmp_path):
    doc = _g(verification=[{"command": "definitely-not-a-real-binary-xyz"}])
    rep = run_graph(doc, MockRunner({}), root=tmp_path, run_commands=True)
    assert not rep.passed
    assert "FileNotFoundError" in rep.command_failures[0]
