"""AGR v1.3: triggers, durability, enforced budgets.

Every test here is falsifiable by something other than a fixture — the lesson
from v1.2, where `attempts`, `parallel_group`, the adapters' dropped subgraphs and
`LLMRunner`'s contract-blind prompt all passed a fully green suite because the
fixtures supplied what the runtime owed.
"""
from __future__ import annotations

import json

import pytest

from agenticgraphs.harness import MockRunner, run_graph
from agenticgraphs.registry import ROOT, iter_graphs, load
from agenticgraphs.triggers import TriggerError, emit
from agenticgraphs.validate import validate_graph_file, validate_schema


def _g(**kw):
    doc = {
        "apiVersion": "agr/v1.3",
        "name": "unit-test-graph",
        "description": "a graph used only by unit tests",
        "category": "devops-sre",
        "nodes": [
            {"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
            {"id": "b", "speciality": "producer", "abilities": ["generate"]},
            {"id": "c", "speciality": "critic", "abilities": ["critique"]},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
        "termination": {"max_steps": 20, "contract": "c runs last"},
    }
    doc.update(kw)
    return doc


_OUT = {"a": {"x": 1}, "b": {"y": 2}, "c": {"z": 3}}


# ------------------------------------------------------------------- C6 budgets


def test_a_step_budget_halts_the_run():
    rep = run_graph(_g(budget={"steps_max": 2}), MockRunner(_OUT))
    assert rep.budget_exhausted
    assert "steps_max=2" in rep.budget_exhausted
    assert not rep.passed
    assert len(rep.trace) < 3


def test_a_usd_budget_halts_the_run():
    rep = run_graph(_g(budget={"usd_max": 0.001}), MockRunner(_OUT))
    assert "usd_max" in rep.budget_exhausted
    assert not rep.passed


def test_a_generous_budget_does_not_interfere():
    rep = run_graph(_g(budget={"steps_max": 100, "usd_max": 50}), MockRunner(_OUT))
    assert not rep.budget_exhausted
    assert rep.trace == ["a", "b", "c"]


def test_no_budget_means_no_ceiling_beyond_max_steps():
    rep = run_graph(_g(), MockRunner(_OUT))
    assert not rep.budget_exhausted


# ---------------------------------------------------------- C7 no ignored fields


def test_no_accepted_and_ignored_fields_remain_in_the_schema():
    """`approval.timeout` and `retries.backoff` were recorded-but-unenforced.

    Carrying them a third version would make the schema a place where a promise
    can live indefinitely without a consumer, which is the exact failure v1.3 set
    out to stop. They are gone, not deferred again.
    """
    schema = json.loads((ROOT / "spec" / "agr-graph.schema.json").read_text())
    node = schema["properties"]["nodes"]["items"]["properties"]
    assert "timeout" not in node["approval"]["properties"]
    assert "backoff" not in node["retries"]["properties"]


def test_no_graph_still_carries_a_removed_field():
    for gp in iter_graphs():
        for n in load(gp)["nodes"]:
            assert "timeout" not in (n.get("approval") or {}), gp
            assert "backoff" not in (n.get("retries") or {}), gp


# ------------------------------------------------------------- C5 journal/resume


def _durable():
    return _g(durability={"checkpoint": "every_node", "resume": True})


def test_journal_records_every_node_when_checkpointing():
    rep = run_graph(_durable(), MockRunner(_OUT))
    assert [e["node"] for e in rep.journal] == ["a", "b", "c"]
    assert rep.journal[0]["out"] == {"x": 1}


def test_no_journal_without_durability():
    assert run_graph(_g(), MockRunner(_OUT)).journal == []


def test_a_killed_run_resumes_to_the_identical_terminal_state(tmp_path):
    """C5 asserts trace *equality*, not 'looks similar'.

    Resume replays journalled frames and skips completed nodes; a resumed node
    routes through the same `_fire` path as a fresh one, so divergence would show
    up here rather than in production.
    """
    doc = _durable()
    full = run_graph(doc, MockRunner(_OUT))

    # Simulate a kill after the first node by truncating the journal.
    journal = tmp_path / "run.jsonl"
    journal.write_text(json.dumps(full.journal[0]) + "\n")

    resumed = run_graph(doc, MockRunner(_OUT), resume_from=journal)
    assert resumed.trace == full.trace
    assert resumed.resumed_nodes == ["a"]
    assert resumed.passed == full.passed


def test_resuming_a_complete_journal_replays_everything(tmp_path):
    doc = _durable()
    full = run_graph(doc, MockRunner(_OUT))
    journal = tmp_path / "run.jsonl"
    journal.write_text("\n".join(json.dumps(e) for e in full.journal) + "\n")

    resumed = run_graph(doc, MockRunner({}), resume_from=journal)
    assert resumed.trace == full.trace
    assert resumed.resumed_nodes == ["a", "b", "c"]


# ---------------------------------------------------------------- C4 triggers


def _triggered(**kw):
    return _g(triggers=[kw])


def test_schedule_compiles_to_a_crontab_line():
    out = emit(_triggered(on="schedule", cron="7 * * * *"), "cron")
    assert "7 * * * * agr eval unit-test-graph" in out


def test_schedule_and_webhook_compile_to_a_github_workflow():
    doc = _g(triggers=[{"on": "schedule", "cron": "7 * * * *"},
                       {"on": "webhook", "source": "github", "event": "pull_request"}])
    out = emit(doc, "github-actions")
    assert "schedule:" in out and "- cron: '7 * * * *'" in out
    assert "pull_request:" in out
    assert "agr eval unit-test-graph" in out


def test_a_signal_github_cannot_express_is_flagged_not_dropped():
    """Silently losing a trigger would be the same class of lie as a silent truncation."""
    doc = _g(triggers=[{"on": "schedule", "cron": "7 * * * *"},
                       {"on": "signal", "expr": "error_budget_burn > 2.0"}])
    out = emit(doc, "github-actions")
    assert "cannot express" in out
    assert "error_budget_burn > 2.0" in out


def test_signal_compiles_to_a_webhook_filter():
    out = json.loads(emit(_triggered(on="signal", expr="burn > 2.0"), "webhook"))
    assert out["match"] == [{"condition": "burn > 2.0"}]
    assert out["run"] == "agr eval unit-test-graph"


def test_a_graph_without_triggers_says_so_rather_than_emitting_nothing():
    with pytest.raises(TriggerError, match="request/response"):
        emit(_g(), "cron")


def test_a_non_github_webhook_is_refused_for_github_actions():
    doc = _triggered(on="webhook", source="stripe", event="invoice.paid")
    with pytest.raises(TriggerError, match="not github"):
        emit(doc, "github-actions")


@pytest.mark.parametrize("target", ["cron", "github-actions", "webhook"])
def test_every_declared_trigger_round_trips_for_at_least_one_target(target):
    """C4: every trigger kind in the registry compiles somewhere."""
    emitted = 0
    for gp in iter_graphs():
        doc = load(gp)
        if not doc.get("triggers"):
            continue
        try:
            out = emit(doc, target)
        except TriggerError:
            continue
        assert doc["name"] in out
        emitted += 1
    assert emitted, f"no registry graph compiles for {target}"


# ------------------------------------------------------------------- registry


def test_registry_graphs_declaring_triggers_also_declare_a_budget():
    """A graph that fires on its own must be bounded, or it is an unbounded loop."""
    for gp in iter_graphs():
        doc = load(gp)
        if doc.get("triggers"):
            assert doc.get("budget"), f"{doc['name']} triggers itself with no budget"


def test_whole_registry_validates():
    bad = {p.parent.name: errs for p in iter_graphs() if (errs := validate_graph_file(p))}
    assert not bad, bad


def test_v13_fields_require_the_v13_apiversion():
    doc = _g(triggers=[{"on": "schedule", "cron": "* * * * *"}])
    doc["apiVersion"] = "agr/v1.2"
    assert not validate_schema(doc, "graph")  # schema is permissive; lint is the gate


# ------------------------------------------------- v1.4: contracts are connected


def test_the_lint_catches_a_verification_key_no_node_produces():
    """D3. The rule that would have caught all four unsatisfiable contracts."""
    from agenticgraphs.validate import lint_graph, unconnected_keys

    doc = _g(apiVersion="agr/v1.4",
             verification=[{"assert": "output.recomputed_effect > 0"}])
    doc["nodes"][0]["outputs"] = ["something_else"]
    assert unconnected_keys(doc) == {"recomputed_effect"}
    assert any("recomputed_effect" in e and e.startswith("lint:") for e in lint_graph(doc))


def test_declaring_the_key_clears_the_lint():
    from agenticgraphs.validate import lint_graph

    doc = _g(apiVersion="agr/v1.4",
             verification=[{"assert": "output.recomputed_effect > 0"}])
    doc["nodes"][0]["outputs"] = ["recomputed_effect"]
    assert not [e for e in lint_graph(doc) if "recomputed_effect" in e]


def test_the_extractor_ignores_comprehension_variables():
    """A regex counted `f`, `v` and `for` as blackboard keys — a wrong number
    that looked like a finding. The AST version does not.
    """
    from agenticgraphs.validate import asserted_keys

    assert asserted_keys("all(f.file and f.line for f in output.findings)") == {"findings"}
    assert asserted_keys("len(output.actions) >= 1 and threshold > 0") == {"actions", "threshold"}


def test_advisories_never_reach_the_error_channel():
    """An earlier draft returned warnings from lint_graph and bricked `agr infuse`,
    which refuses on any lint output: 'infusion rejected by gate: warn: ...'.
    """
    from agenticgraphs.validate import lint_advisories, lint_graph

    doc = _g(apiVersion="agr/v1.2", verification=[{"assert": "output.nope > 0"}])
    doc["nodes"][0]["outputs"] = ["something_else"]
    assert not [e for e in lint_graph(doc) if "nope" in e]
    assert any("nope" in w for w in lint_advisories(doc))


def test_every_registry_graph_has_a_connected_contract():
    """D1: 123 unmet keys at the start of v1.4, 0 now."""
    from agenticgraphs.validate import unconnected_keys

    unmet = {load(gp)["name"]: sorted(unconnected_keys(load(gp)))
             for gp in iter_graphs() if unconnected_keys(load(gp))}
    assert not unmet, unmet


def test_every_registry_graph_is_fully_declared():
    """v1.4 connected verification to producers; v1.5 gave every dependent node one."""
    from agenticgraphs.registry import SPEC_VERSION
    from agenticgraphs.validate import silent_nodes, unconnected_keys

    stragglers = [load(gp)["name"] for gp in iter_graphs()
                  if load(gp)["apiVersion"] != SPEC_VERSION]
    assert not stragglers, stragglers
    silent = {load(gp)["name"]: silent_nodes(load(gp))
              for gp in iter_graphs() if silent_nodes(load(gp))}
    assert not silent, silent
    unmet = {load(gp)["name"]: sorted(unconnected_keys(load(gp)))
             for gp in iter_graphs() if unconnected_keys(load(gp))}
    assert not unmet, unmet
