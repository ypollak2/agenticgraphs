"""The journal `--resume-from` reads is the journal `--journal` writes, and its
shape is pinned here so docs/agr-v1.8.md and the code cannot drift (R2-10).

Nothing wrote the file before: resume shipped in v1.3 with a consumer and no
producer (2026-09-04 audit, D3-04).
"""
from __future__ import annotations

import json

from agenticgraphs.cli import main
from agenticgraphs.evalcmd import JOURNAL_KEYS, write_journal
from agenticgraphs.harness import MockRunner, run_graph
from agenticgraphs.registry import SPEC_VERSION

GOAL = {"goal": "a stated subject"}


def _durable():
    return {
        "apiVersion": SPEC_VERSION, "name": "journal-unit", "category": "software-engineering",
        "description": "journal fixture",
        "nodes": [{"id": "a", "speciality": "analyst", "abilities": ["analyze"], "outputs": ["x"]},
                  {"id": "b", "speciality": "producer", "abilities": ["generate"], "outputs": ["y"]}],
        "edges": [{"from": "a", "to": "b"}],
        "termination": {"max_steps": 5, "contract": "b after a"},
        "durability": {"checkpoint": "every_node", "resume": True},
        "verification": [{"assert": "y == 2"}],
    }


def test_journal_records_carry_exactly_node_and_out(tmp_path):
    rep = run_graph(_durable(), MockRunner({"a": {"x": 1}, "b": {"y": 2}}), inputs=GOAL)
    path = tmp_path / "run.jsonl"
    write_journal(path, rep.journal)
    lines = [json.loads(ln) for ln in path.read_text().splitlines()]
    assert [set(e) for e in lines] == [set(JOURNAL_KEYS)] * 2
    assert [e["node"] for e in lines] == ["a", "b"]
    assert lines[0]["out"] == {"x": 1}


def test_a_written_journal_resumes_the_run_it_came_from(tmp_path):
    doc = _durable()
    full = run_graph(doc, MockRunner({"a": {"x": 1}, "b": {"y": 2}}), inputs=GOAL)
    path = tmp_path / "run.jsonl"
    write_journal(path, full.journal[:1])  # killed after a
    resumed = run_graph(doc, MockRunner({"a": {"x": 999}, "b": {"y": 2}}),
                        resume_from=path, inputs=GOAL)
    assert resumed.resumed_nodes == ["a"]
    assert resumed.trace == full.trace
    assert resumed.frames_for("a")[0]["out"] == {"x": 1}, "resume re-ran a instead of replaying it"


def test_agr_eval_journal_writes_what_resume_from_reads(tmp_path, capsys, monkeypatch):
    """End to end through the CLI on a shipped graph that checkpoints. The
    profile write is stubbed: `--no-replay` computes a profile without the live
    block, and a test must not land that in the evidence store."""
    from agenticgraphs import evalcmd

    monkeypatch.setattr(evalcmd, "write_profile", lambda *a, **k: False)
    code = main(["eval", "deploy-canary-verifier", "--no-replay", "--journal", str(tmp_path)])
    capsys.readouterr()
    assert code == 0
    files = sorted(tmp_path.glob("*.jsonl"))
    assert files, "no journal written for a graph with durability.checkpoint: every_node"
    for f in files:
        for ln in f.read_text().splitlines():
            assert set(json.loads(ln)) == set(JOURNAL_KEYS), (f.name, ln)
    code = main(["eval", "deploy-canary-verifier", "--no-replay", "--resume-from", str(files[0])])
    capsys.readouterr()
    assert code == 0


def test_no_journal_file_for_a_graph_that_does_not_checkpoint(tmp_path, capsys, monkeypatch):
    from agenticgraphs import evalcmd

    monkeypatch.setattr(evalcmd, "write_profile", lambda *a, **k: False)
    main(["eval", "code-review-pipeline", "--no-replay", "--journal", str(tmp_path)])
    capsys.readouterr()
    assert not list(tmp_path.glob("*.jsonl"))
