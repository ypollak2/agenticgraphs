import pytest

from agenticgraphs.compose import ComposeError, compose
from agenticgraphs.harness import MockRunner, run_graph
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import load
from agenticgraphs.validate import lint_graph, validate_schema


def test_compose_compatible_pair_validates_and_runs():
    a = load(find_graph("incident-triage-router"))
    b = load(find_graph("ticket-triage-swarm"))
    doc, warnings = compose(a, b)

    assert validate_schema(doc, "graph") == []
    assert lint_graph(doc) == []

    # all four node ids collide between the two source graphs, so every id
    # should have been namespaced
    ids = {n["id"] for n in doc["nodes"]}
    assert ids == {"a-route", "a-branch-simple", "a-branch-complex", "a-verify",
                   "b-route", "b-branch-simple", "b-branch-complex", "b-verify"}
    assert any("namespaced colliding node ids" in w for w in warnings)

    # A's sole terminal (a-verify) bridges into B's sole entry (b-route)
    assert {"from": "a-verify", "to": "b-route"} in doc["edges"]
    assert doc["termination"]["max_steps"] == a["termination"]["max_steps"] + b["termination"]["max_steps"]

    rep = run_graph(doc, MockRunner({
        "a-route": {"complexity": "high"},
        "a-branch-complex": {},
        "a-verify": {},
        "b-route": {"complexity": "high"},
        "b-branch-complex": {},
        "b-verify": {},
    }))
    assert not rep.hit_step_cap
    assert "a-route" in rep.trace and "b-route" in rep.trace
    assert "a-verify" in rep.trace and "b-verify" in rep.trace


def test_compose_incompatible_contract_raises():
    a = load(find_graph("incident-triage-router"))
    b = load(find_graph("code-review-pipeline"))
    with pytest.raises(ComposeError, match="risk"):
        compose(a, b)


def test_compose_allow_gaps_bypasses_with_warning():
    a = load(find_graph("incident-triage-router"))
    b = load(find_graph("code-review-pipeline"))
    doc, warnings = compose(a, b, allow_gaps=True)
    assert validate_schema(doc, "graph") == []
    assert lint_graph(doc) == []
    assert any("bypassed via --allow-gaps" in w for w in warnings)
