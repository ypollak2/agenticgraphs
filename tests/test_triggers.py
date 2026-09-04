"""`triggers.py` had no test file of its own (2026-09-04 audit, D8-04 / R3-09).

v1.3's rule: no field ships without an executing consumer. These pin the consumer.
"""
from __future__ import annotations

import pytest
import yaml

from agenticgraphs.triggers import TriggerError, emit, emit_cron, emit_github_actions


def _doc(*triggers):
    return {"name": "nightly-thing", "description": "Runs nightly.\nMore prose.",
            "triggers": list(triggers)}


def test_cron_lines_one_per_schedule_trigger():
    out = emit_cron(_doc({"on": "schedule", "cron": "0 6 * * 1-5"},
                         {"on": "schedule", "cron": "30 18 * * *"}))
    lines = out.strip().splitlines()
    assert lines[0].startswith("# nightly-thing")
    assert lines[1:] == ["0 6 * * 1-5 agr eval nightly-thing", "30 18 * * * agr eval nightly-thing"]


def test_cron_refuses_a_graph_with_no_schedule():
    with pytest.raises(TriggerError, match="no schedule trigger"):
        emit_cron(_doc({"on": "webhook", "source": "github", "event": "pull_request"}))


def test_github_actions_on_block_mirrors_the_declared_triggers():
    wf = yaml.safe_load(emit_github_actions(_doc(
        {"on": "schedule", "cron": "0 6 * * 1-5"},
        {"on": "webhook", "source": "github", "event": "pull_request"})))
    on = wf.get("on") or wf.get(True)  # PyYAML parses a bare `on:` key as True
    assert "schedule" in on and "pull_request" in on


def test_a_signal_github_cannot_express_is_flagged_not_dropped():
    out = emit_github_actions(_doc({"on": "signal", "expr": "error_rate > 0.05"},
                                   {"on": "schedule", "cron": "0 6 * * *"}))
    assert "signal" in out.lower() and "error_rate > 0.05" in out


def test_emit_dispatches_by_target_and_refuses_unknown_ones():
    doc = _doc({"on": "schedule", "cron": "0 6 * * *"})
    assert "agr eval" in emit(doc, "cron")
    with pytest.raises(TriggerError, match="unknown target"):
        emit(doc, "kubernetes-cronjob")
    with pytest.raises(TriggerError, match="no triggers"):
        emit({"name": "plain", "description": "d"}, "cron")
