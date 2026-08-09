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


def _undeclared(name, when=None, needs=None):
    """A graph that declares no I/O — the shape `compose`'s heuristic exists for.

    Every registry graph declares outputs since v1.4, so the heuristic path is no
    longer reachable from the registry. These tests build the shape directly
    rather than deleting the coverage.
    """
    return {
        "apiVersion": "agr/v1",
        "name": name,
        "description": "a graph used only by compose tests",
        "category": "software-engineering",
        "nodes": [
            {"id": "one", "speciality": "analyst", "abilities": ["analyze"]},
            {"id": "two", "speciality": "producer", "abilities": ["generate"]},
        ],
        "edges": [{"from": "one", "to": "two", **({"when": when} if when else {})}],
        "termination": {"max_steps": 8, "contract": "two runs after one"},
        "verification": [{"assert": needs or "true"}],
    }


def test_compose_incompatible_contract_raises():
    """The heuristic still catches a gap when neither side declares a contract."""
    a = _undeclared("producer-graph")
    b = _undeclared("consumer-graph", when="risk >= medium")
    with pytest.raises(ComposeError, match="risk"):
        compose(a, b)


def test_compose_allow_gaps_bypasses_with_warning():
    a = _undeclared("producer-graph")
    b = _undeclared("consumer-graph", when="risk >= medium")
    doc, warnings = compose(a, b, allow_gaps=True)
    assert validate_schema(doc, "graph") == []
    assert any("bypassed via --allow-gaps" in w for w in warnings)


def test_registry_graphs_now_compose_on_declared_contracts():
    """v1.4's payoff: the pair that only a heuristic could judge is now checked.

    `incident-triage-router` -> `code-review-pipeline` used to raise on a guessed
    `risk` dependency. Both declare their I/O now, so the verdict comes from the
    contract rather than from identifiers scraped out of edge conditions.
    """
    from agenticgraphs.compose import contract_basis

    a = load(find_graph("incident-triage-router"))
    b = load(find_graph("code-review-pipeline"))
    assert contract_basis(a, b) == "declared"
    doc, _ = compose(a, b)
    assert validate_schema(doc, "graph") == []
