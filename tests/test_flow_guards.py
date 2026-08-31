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
