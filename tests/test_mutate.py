
import yaml

from agenticgraphs.inspect import find_graph
from agenticgraphs.mutate import infuse, optimize
from agenticgraphs.registry import load


class _snapshot:
    """Restore a graph directory from a pre-test snapshot, not from git HEAD.

    These tests mutate two real registry graphs. Restoring with
    `git checkout -- <dir>` reverts to HEAD, which silently discards any
    *uncommitted* edit to those graphs — during the v1.4 migration it wiped the
    declarations added to `code-review-pipeline` and `cost-routed-research`
    on every test run, and the loss looked like a bug in the migration script.
    A snapshot of the working tree has no such coupling.
    """

    def __init__(self, path):
        self.dir = path.parent
        self.saved = {p: p.read_bytes() for p in self.dir.iterdir() if p.is_file()}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for p in self.dir.iterdir():
            if p.is_file() and p not in self.saved:
                p.unlink()
        for p, data in self.saved.items():
            p.write_bytes(data)
        return False


def test_infuse_adds_ability_and_lineage():
    g = find_graph("code-review-pipeline")
    with _snapshot(g):
        res = infuse("code-review-pipeline", "style-review", "classify_risk")
        assert res["changed"]
        doc = load(g)
        node = next(n for n in doc["nodes"] if n["id"] == "style-review")
        assert "classify_risk" in node["abilities"]
        lineage = yaml.safe_load((g.parent / "lineage.yaml").read_text())
        assert lineage["mutations"][-1]["op"] == "infuse"


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
    with _snapshot(g):
        optimize("cost-routed-research", apply=True)
        doc = load(g)
        assert doc["termination"]["max_steps"] <= 20  # never grows
