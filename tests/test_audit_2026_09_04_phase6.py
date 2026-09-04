"""Phase 6 of the 2026-09-04 gap audit: the MCP surface, autonomy isolation, and
concurrent parallel groups.

Each test names the finding it closes (docs/plans/audit-gaps-2026-09-04.md).
"""
from __future__ import annotations

import json
import subprocess
import threading
import time

import pytest
import yaml

from agenticgraphs.harness import MockRunner, run_graph
from agenticgraphs.registry import ROOT, SPEC_VERSION

GOAL = {"goal": "a stated subject"}


# ------------------------------------------------------------------ D3-01 / R6-03


def _swarm(n_workers=3):
    nodes = [{"id": "plan", "speciality": "planner", "abilities": ["decompose_goal"], "outputs": ["tasks"]}]
    edges = []
    for i in range(n_workers):
        nodes.append({"id": f"w{i}", "speciality": "analyst", "abilities": ["analyze"],
                      "parallel_group": "workers", "outputs": [f"r{i}"]})
        edges.append({"from": "plan", "to": f"w{i}"})
    nodes.append({"id": "merge", "speciality": "reducer", "abilities": ["reduce_merge"], "join": "all"})
    edges += [{"from": f"w{i}", "to": "merge"} for i in range(n_workers)]
    return {"apiVersion": SPEC_VERSION, "name": "swarm-unit", "category": "cat", "description": "d",
            "nodes": nodes, "edges": edges, "termination": {"max_steps": 20, "contract": "merge runs"},
            "verification": [{"assert": "r0 == 0 and r1 == 1 and r2 == 2"}]}


class _Concurrent:
    """Records which nodes were in flight at the same time."""

    name = "mock"

    def __init__(self):
        self.active, self.peak, self.lock = 0, 0, threading.Lock()

    def run(self, node, bb):
        if node["id"].startswith("w"):
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            time.sleep(0.05)
            with self.lock:
                self.active -= 1
            return {f"r{node['id'][1:]}": int(node["id"][1:])}
        return {"tasks": [1, 2, 3]} if node["id"] == "plan" else {}


def test_ready_members_of_a_parallel_group_run_in_one_round():
    runner = _Concurrent()
    rep = run_graph(_swarm(), runner, inputs=GOAL)
    assert rep.passed, rep.assert_failures
    assert rep.trace == ["plan", "w0", "w1", "w2", "merge"]
    assert rep.steps == 5, "steps still count node executions"
    assert rep.rounds == 3, "plan, the batch, merge"
    assert runner.peak == 3, "the three workers were not in flight together"


def test_a_failing_member_does_not_lose_its_siblings():
    class _OneFails(_Concurrent):
        def run(self, node, bb):
            if node["id"] == "w1":
                return {"error": "w1 blew up"}
            return super().run(node, bb)

    doc = _swarm()
    doc["verification"] = [{"assert": "r0 == 0 and r2 == 2"}]
    doc["edges"].append({"from": "w1", "to": "merge", "kind": "error"})
    rep = run_graph(doc, _OneFails(), inputs=GOAL)
    assert "w0" in rep.trace and "w2" in rep.trace
    assert rep.frames_for("w0")[0]["out"] == {"r0": 0}
    assert rep.frames_for("w2")[0]["out"] == {"r2": 2}


def test_the_v1_trace_lock_still_holds_with_concurrency():
    """`steps` and trace order are unchanged by batching; only `rounds` moves."""
    lock = json.loads((ROOT / "tests" / "fixtures" / "v1_trace_lock.json").read_text())
    from agenticgraphs.evalcmd import case_inputs
    from agenticgraphs.inspect import find_graph
    from agenticgraphs.registry import cases_path, load

    doc = load(find_graph("ab-test-analysis"))
    cases = yaml.safe_load(cases_path("ab-test-analysis").read_text())["cases"]
    for case, expected in zip(cases, lock["ab-test-analysis"], strict=True):
        rep = run_graph(doc, MockRunner(case["node_outputs"]), inputs=case_inputs(case))
        assert rep.trace == expected["trace"] and rep.steps == expected["steps"]
        assert rep.rounds < rep.steps


# ------------------------------------------------------------------ D7-04 / R6-01


@pytest.fixture(scope="module")
def tools():
    pytest.importorskip("mcp", reason="mcp extra not installed")
    from agenticgraphs.mcp_server import create_server

    server = create_server()
    return {name: t.fn for name, t in server._tool_manager._tools.items()}


def test_validate_graph_tool_lints_a_candidate(tools):
    from agenticgraphs.inspect import find_graph

    good = find_graph("verifier-swarm").read_text()
    assert tools["validate_graph"](good) == []
    bad = yaml.safe_load(good)
    bad["edges"].append({"from": "planner", "to": "ghost"})
    errs = tools["validate_graph"](yaml.safe_dump(bad))
    assert any("unknown node" in e for e in errs)
    assert tools["validate_graph"]("- not: a mapping") == ["not a mapping"]


def test_run_graph_tool_runs_mock_cases_and_writes_nothing(tools):
    from agenticgraphs.inspect import find_graph

    before = (find_graph("code-review-pipeline").parent / "profile.json").read_bytes()
    block = tools["run_graph"]("code-review-pipeline")
    assert block["runner"] == "mock" and block["pass_rate"] == 1.0
    assert block["results"][0]["failure_kinds"] == []
    assert (find_graph("code-review-pipeline").parent / "profile.json").read_bytes() == before


def test_run_graph_tool_gates_live_and_commands(tools, monkeypatch):
    monkeypatch.delenv("AGR_MCP_TOKEN", raising=False)
    monkeypatch.delenv("AGR_AUTONOMOUS_ALLOW_EXECUTE", raising=False)
    with pytest.raises(ValueError, match="AGR_MCP_TOKEN"):
        tools["run_graph"]("code-review-pipeline", live=True)
    with pytest.raises(ValueError, match="ALLOW_EXECUTE"):
        tools["run_graph"]("code-review-pipeline", run_commands=True)
    with pytest.raises(ValueError, match="no graph"):
        tools["run_graph"]("no-such-graph")


def test_list_abilities_and_specialities_tools(tools):
    abilities = {a["name"]: a for a in tools["list_abilities"]()}
    assert abilities["run_command"]["bound"] is True and abilities["run_command"]["risk"] == "execute"
    assert abilities["cut_release"]["bound"] is False and abilities["cut_release"]["idempotent"] is False
    specs = {s["name"]: s for s in tools["list_specialities"]()}
    assert "shadow_write" in specs["migrator"]["optional"]


def test_get_profile_and_diff_graphs_tools(tools):
    prof = tools["get_profile"]("vendor-comparison-matrix")
    assert "refs" in prof and prof["measured"]["runner"] == "mock"
    diff = tools["diff_graphs"]("returns-triage", "ticket-triage-swarm")
    assert diff.startswith("--- returns-triage/graph.yaml") and "+++ ticket-triage-swarm/graph.yaml" in diff
    with pytest.raises(ValueError, match="no graph named 'nope'"):
        tools["diff_graphs"]("returns-triage", "nope")


# ------------------------------------------------------------------ D7-02 / R6-02


@pytest.fixture
def repo_clone(tmp_path):
    dst = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(dst)], check=True)
    subprocess.run(["git", "-C", str(dst), "checkout", "-q", "-B", "agr-test-base"], check=True)
    subprocess.run(["git", "-C", str(dst), "config", "user.name", "Autonomy Test"], check=True)
    subprocess.run(["git", "-C", str(dst), "config", "user.email", "t@example.com"], check=True)
    return dst


def test_optimize_autonomous_lands_on_auto_mutations_not_the_checkout(monkeypatch, repo_clone):
    """One flag used to mean two blast radii: MCP persist was isolated, optimize
    wrote into the live checkout (D7-02)."""
    from agenticgraphs.mutate import optimize_autonomous

    monkeypatch.setenv("AGR_AUTONOMOUS", "1")
    gpath = repo_clone / "graphs" / "software-engineering" / "code-review-pipeline" / "graph.yaml"
    doc = yaml.safe_load(gpath.read_text())
    doc["edges"].append(dict(doc["edges"][1]))  # a duplicate edge the optimizer dedupes
    gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=120))
    subprocess.run(["git", "-C", str(repo_clone), "commit", "-qam", "dup edge"], check=True)

    res = optimize_autonomous("code-review-pipeline", root=repo_clone)
    assert res["changed"] and res["branch"] == "auto/mutations" and res["commit"]
    head = subprocess.run(["git", "-C", str(repo_clone), "symbolic-ref", "--short", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert head == "agr-test-base"
    tip = subprocess.run(["git", "-C", str(repo_clone), "rev-parse", "auto/mutations"],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert tip == res["commit"]
    base_tip = subprocess.run(["git", "-C", str(repo_clone), "rev-parse", "agr-test-base"],
                              capture_output=True, text=True, check=True).stdout.strip()
    assert base_tip != tip, "the optimizer committed onto the checked-out branch"


def test_optimize_autonomous_refuses_without_the_opt_in(monkeypatch):
    from agenticgraphs.autonomy import AutonomyError
    from agenticgraphs.mutate import optimize_autonomous

    monkeypatch.delenv("AGR_AUTONOMOUS", raising=False)
    with pytest.raises(AutonomyError):
        optimize_autonomous("code-review-pipeline")
