"""`evalcmd.py` had no test file of its own (2026-09-04 audit, D8-04 / R3-09).

The depth ladder, case seeding, and recording selection are the parts a
scoreboard number rests on; each is pinned here directly.
"""
from __future__ import annotations

import json

from agenticgraphs.evalcmd import _recordings, case_inputs, eval_graph, verification_depth
from agenticgraphs.registry import SPEC_VERSION


def test_depth_ladder_grades_evidence_not_claims():
    cmd = {"verification": [{"command": "pytest -q"}]}
    asr = {"verification": [{"assert": "x == 1"}]}
    prose = {"verification": [{"describe": "it works"}]}
    assert verification_depth(cmd, "mock") == "command"
    assert verification_depth(asr, "mock") == "assert-fixture"
    assert verification_depth(asr, "llm:qwen") == "assert-live"
    assert verification_depth(asr, "llm-replay:qwen") == "assert-live"
    assert verification_depth(asr, "tools:qwen", grounded=True) == "assert-grounded"
    assert verification_depth(asr, "llm:qwen", grounded=False) == "assert-live"
    assert verification_depth(prose, "llm:qwen") == "describe-only"


def test_case_inputs_seed_goal_and_inputs_and_an_explicit_goal_wins():
    case = {"goal": "from the case", "inputs": {"threshold": 3}}
    assert case_inputs(case) == {"threshold": 3, "goal": "from the case"}
    assert case_inputs(case, goal="override")["goal"] == "override"
    assert case_inputs({}) == {}


def test_recordings_exclude_superseded_and_wrong_spec_files(tmp_path):
    live = tmp_path / "graphs" / "cat" / "g" / "live"
    live.mkdir(parents=True)
    (live / "case@m.json").write_text(json.dumps({"spec": SPEC_VERSION, "node_outputs": {}}))
    (live / "case@old.json").write_text(json.dumps({"spec": "agr/v1.7", "node_outputs": {}}))
    (live / "case@retired.json").write_text(json.dumps({"spec": SPEC_VERSION, "superseded_by": "x",
                                                        "node_outputs": {}}))
    (live / "other@m.json").write_text(json.dumps({"spec": SPEC_VERSION, "node_outputs": {}}))
    # _recordings resolves the live dir through the registry layout under `root`
    from agenticgraphs import registry

    orig = registry.live_dir
    try:
        registry.live_dir = lambda name, root=None: live
        import agenticgraphs.evalcmd as ev

        ev.live_dir = registry.live_dir
        found = [p.name for p in _recordings(tmp_path, "g", "case")]
    finally:
        registry.live_dir = orig
        ev.live_dir = orig
    assert found == ["case@m.json"]


def test_eval_graph_refuses_a_graph_without_golden_cases(tmp_path, monkeypatch):
    import pytest

    with pytest.raises(SystemExit, match="no graph named"):
        eval_graph("no-such-graph", write=False)


def test_eval_graph_reports_the_taxonomy_per_case():
    prof = eval_graph("code-review-pipeline", write=False)
    for r in prof["measured"]["results"]:
        assert set(r) >= {"parse_failures", "gate_refused", "timeouts", "failure_kinds",
                          "overwritten_inputs"}
        assert r["failure_kinds"] == []
