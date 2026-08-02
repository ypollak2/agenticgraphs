import subprocess

import yaml

from agenticgraphs.inspect import find_graph
from agenticgraphs.mutate import infuse, optimize
from agenticgraphs.registry import load


def _git_restore(path):
    subprocess.run(["git", "checkout", "--", str(path.parent)], cwd=path.parents[3], check=True)


def test_infuse_adds_ability_and_lineage():
    g = find_graph("code-review-pipeline")
    try:
        res = infuse("code-review-pipeline", "style-review", "classify_risk")
        assert res["changed"]
        doc = load(g)
        node = next(n for n in doc["nodes"] if n["id"] == "style-review")
        assert "classify_risk" in node["abilities"]
        lineage = yaml.safe_load((g.parent / "lineage.yaml").read_text())
        assert lineage["mutations"][-1]["op"] == "infuse"
    finally:
        _git_restore(g)


def test_infuse_unknown_ability_rejected():
    try:
        infuse("code-review-pipeline", "triage", "summon_demons")
        raise AssertionError("should have exited")
    except SystemExit as e:
        assert "unknown ability" in str(e)


def test_optimize_dry_run_tightens_measured_budget():
    g = find_graph("verifier-swarm")
    res = optimize("verifier-swarm", apply=False)
    assert any("max_steps" in n for n in res["notes"])   # profile says worst-case 7 << 30
    assert res["changed"] is False and load(g)["termination"]["max_steps"] == 30  # dry-run untouched


def test_optimize_apply_survives_gate_and_cases():
    g = find_graph("cost-routed-research")
    try:
        optimize("cost-routed-research", apply=True)
        doc = load(g)
        assert doc["termination"]["max_steps"] <= 20  # never grows
    finally:
        _git_restore(g)
