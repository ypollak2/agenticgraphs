"""AGR v1.7 — the goal a graph must be given before it may run.

`state.inputs` was declared by 31 graphs from v1.1 onward and seeded by nothing:
`run_graph` opened with `bb = {}`, so the linter vouched for values that never
arrived. These tests hold both halves of the fix — that entry inputs reach the
blackboard, and that a graph which cannot know its subject refuses rather than
inventing one.
"""
from __future__ import annotations

import pytest
import yaml

from agenticgraphs.evalcmd import case_inputs
from agenticgraphs.harness import MockRunner, run_graph
from agenticgraphs.registry import SPEC_VERSION, cases_path, iter_graphs, load
from agenticgraphs.validate import lint_graph


def _g(**kw) -> dict:
    doc = {
        "apiVersion": SPEC_VERSION, "name": "t", "description": "d", "category": "c",
        "nodes": [{"id": "a", "speciality": "supervisor", "outputs": ["k"]}],
        "edges": [], "termination": {"max_steps": 3},
    }
    doc.update(kw)
    return doc


def _required(**over) -> dict:
    goal = {"required": True, "description": "the thing to work on"}
    goal.update(over)
    return _g(goal=goal, state={"inputs": ["goal"]})


# ------------------------------------------------------------------ J1: seeding


def test_entry_inputs_reach_the_blackboard():
    """The half that was missing for five versions."""
    seen = {}

    class Spy(MockRunner):
        def run(self, node, bb):
            seen.update(bb)
            return {"k": 1}

    run_graph(_g(state={"inputs": ["repo"]}), Spy({}), inputs={"repo": "acme/web"})
    assert seen["repo"] == "acme/web"


def test_passing_no_inputs_is_identical_to_before():
    """Pre-v1.7 behaviour is the default, so the v1 trace lock still holds."""
    rep = run_graph(_g(), MockRunner({"a": {"k": 1}}))
    assert rep.passed and rep.trace == ["a"]


def test_every_graph_declaring_state_inputs_declares_a_goal():
    """Needing something at entry and requiring a goal are the same condition."""
    missing = [
        d["name"] for d in map(load, iter_graphs())
        if (d.get("state") or {}).get("inputs") and not (d.get("goal") or {}).get("required")
    ]
    assert not missing, missing


# ------------------------------------------------------------------ J3: refusal


def test_a_required_goal_that_is_absent_runs_no_node():
    rep = run_graph(_required(), MockRunner({"a": {"k": 1}}))
    assert not rep.passed
    assert rep.goal_missing == "the thing to work on"
    assert rep.trace == [] and rep.steps == 0


def test_the_refusal_does_not_pollute_the_trace():
    """`trace` means 'nodes that executed'; callers compare it against node ids."""
    rep = run_graph(_required(), MockRunner({"a": {"k": 1}}))
    assert all(t in {"a"} for t in rep.trace)


def test_a_supplied_goal_lets_the_graph_run():
    rep = run_graph(_required(), MockRunner({"a": {"k": 1}}), inputs={"goal": "ship it"})
    assert not rep.goal_missing and rep.trace == ["a"]


def test_an_optional_goal_never_refuses():
    doc = _g(goal={"required": False, "description": "d"}, state={"inputs": ["goal"]})
    assert run_graph(doc, MockRunner({"a": {"k": 1}})).passed


def test_a_trigger_supplied_goal_is_exempt_only_when_it_has_triggers():
    trig = [{"kind": "cron", "cron": "0 9 * * *"}]
    exempt = _required(supplied_by_trigger=True) | {"triggers": trig}
    assert not run_graph(exempt, MockRunner({"a": {"k": 1}})).goal_missing

    # The exemption is the trigger, not the flag: without one, it still refuses.
    assert run_graph(_required(supplied_by_trigger=True), MockRunner({"a": {"k": 1}})).goal_missing


def test_the_refusal_quotes_what_the_caller_should_bring():
    """A refusal that cannot say what it wants is not actionable."""
    rep = run_graph(_required(description="the PR to review"), MockRunner({}))
    assert rep.goal_missing == "the PR to review"


# -------------------------------------------------------------------- J4: lints


@pytest.mark.parametrize("doc,fragment", [
    (_g(goal={"required": True, "description": "d"}),
     "state.inputs does not list 'goal'"),
    (_g(goal={"required": True}, state={"inputs": ["goal"]}),
     "no goal.description"),
    (_g(goal={"required": True, "description": "d"}, state={"inputs": ["goal"]},
        triggers=[{"kind": "cron", "cron": "0 9 * * *"}]),
     "no goal.supplied_by_trigger"),
    (_g(nodes=[{"id": "a", "speciality": "supervisor", "inputs": ["goal"], "outputs": ["k"]}]),
     "declares no goal block"),
    (_g(apiVersion="agr/v1.5", goal={"required": False}),
     f"bump to '{SPEC_VERSION}'"),
])
def test_lint_catches(doc, fragment):
    assert any(fragment in e for e in lint_graph(doc)), lint_graph(doc)


def test_a_well_formed_goal_lints_clean():
    assert not [e for e in lint_graph(_required()) if "goal" in e]


# ------------------------------------------------------- the migrated registry


def test_every_required_goal_is_reachable_from_its_golden_cases():
    """A required goal the fixtures cannot supply would make every case refuse."""
    offenders = []
    for gp in iter_graphs():
        doc = load(gp)
        if not (doc.get("goal") or {}).get("required"):
            continue
        cases_file = cases_path(doc["name"])
        if not cases_file.exists():
            continue
        for case in yaml.safe_load(cases_file.read_text())["cases"]:
            if not case_inputs(case).get("goal"):
                offenders.append(f"{doc['name']}/{case['id']}")
    assert not offenders, offenders
