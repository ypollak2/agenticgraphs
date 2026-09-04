"""Phase 1 of the 2026-09-04 gap audit: crashes, safety, and evidence-store side effects.

Each test names the finding it closes (docs/plans/audit-gaps-2026-09-04.md) and
guards the property, not the patch, so the next refactor cannot quietly undo it.
"""
from __future__ import annotations

import asyncio
import copy
import json

import pytest
import yaml

from agenticgraphs import bindings, evalcmd, mcp_server
from agenticgraphs.compose import compose_by_reference
from agenticgraphs.harness import _AGG, run_graph
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import ROOT, SPEC_VERSION, load
from agenticgraphs.validate import lint_graph, validate_schema

GOAL = {"goal": "a stated subject, so the graph does not invent one"}


def _g(**kw):
    doc = {
        "apiVersion": SPEC_VERSION,
        "name": "unit-test-graph",
        "description": "a graph used only by unit tests",
        "category": "software-engineering",
        "nodes": [
            {"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
            {"id": "b", "speciality": "producer", "abilities": ["generate"]},
        ],
        "edges": [{"from": "a", "to": "b"}],
        "termination": {"max_steps": 20, "contract": "b runs after a"},
    }
    doc.update(kw)
    return doc


# ------------------------------------------------------------------ D1-01 / R1-01


@pytest.mark.parametrize("op, values, expected", [
    ("median", [3, None, 5], 5),
    ("best", [3, None, 5], 5),
    ("median", [None, None], None),
])
def test_aggregate_over_a_partially_failed_fan_out_does_not_crash(op, values, expected):
    """`on_partial: continue` puts None in the list for every failed shard;
    `median`/`best` raised TypeError on it and took the run down (D1-01)."""
    assert _AGG[op]([v for v in values if v is not None]) == expected


def test_a_failed_shard_is_dropped_from_median_and_best_at_run_time():
    doc = _g(
        nodes=[{"id": "split", "speciality": "analyst", "abilities": ["analyze"],
                "outputs": ["shards"]},
               {"id": "work", "speciality": "worker", "abilities": ["execute_step"],
                "fan_out": {"over": "shards"}, "outputs": ["score"]},
               {"id": "pick", "speciality": "judge", "abilities": ["adjudicate"],
                "aggregate": {"op": "best", "over": "score"}}],
        edges=[{"from": "split", "to": "work"}, {"from": "work", "to": "pick"}],
        verification=[{"assert": "score == 30"}],
    )

    class _OneShardFails:
        name = "mock"

        def run(self, node, bb):
            if node["id"] == "split":
                return {"shards": [1, 2, 3]}
            if node["id"] == "work":
                if bb["shard"] == 2:
                    return {"error": "shard 2 blew up"}
                return {"score": bb["shard"] * 10}
            return {}

    rep = run_graph(doc, _OneShardFails(), inputs=GOAL)
    assert rep.trace == ["split", "work", "pick"], rep.trace
    assert rep.passed, rep.assert_failures
    work = rep.frames_for("work")
    assert len(work) == 3


# ------------------------------------------------------------------ D3-02 / R1-02


def test_read_diff_reports_a_missing_git_instead_of_hanging_or_raising(tmp_path, monkeypatch):
    import subprocess

    def boom(*a, **kw):
        assert kw.get("timeout"), "subprocess.run called without a timeout"
        raise subprocess.TimeoutExpired(cmd="git", timeout=kw["timeout"])

    monkeypatch.setattr(subprocess, "run", boom)
    out = bindings._read_diff({"ref": "HEAD"}, tmp_path, [])
    assert out["hunks"] == [] and "TimeoutExpired" in out["error"]


# ------------------------------------------------------------------ D3-06 / R1-03


def test_recorded_local_models_price_at_zero_measured_not_estimated():
    from agenticgraphs.harness import _spend

    class _R:
        model = "qwen3-coder:30b"
        usage = {"calls": 3, "prompt_tokens": 1000, "completion_tokens": 500}

    spent, measured = _spend(_R(), steps=3)
    assert spent == 0.0 and measured is True


# ------------------------------------------------------------------ D6-04 / R1-04


def test_eval_graph_without_write_leaves_the_evidence_store_untouched():
    gpath = find_graph("code-review-pipeline")
    before = (gpath.parent / "profile.json").read_bytes()
    evalcmd.eval_graph("code-review-pipeline", write=False)
    assert (gpath.parent / "profile.json").read_bytes() == before


def test_write_profile_only_writes_when_content_changed(tmp_path):
    gpath = tmp_path / "graph.yaml"
    gpath.write_text("name: x\n")
    prof = {"structural": {"nodes": 3}, "measured": {"date": "2026-01-01", "pass_rate": 1.0}}
    assert evalcmd.write_profile(gpath, prof) is True
    later = copy.deepcopy(prof)
    later["measured"]["date"] = "2026-12-31"
    assert evalcmd.write_profile(gpath, later) is False, "a date-only change rewrote the file"
    assert json.loads((tmp_path / "profile.json").read_text())["measured"]["date"] == "2026-01-01"
    later["measured"]["pass_rate"] = 0.5
    assert evalcmd.write_profile(gpath, later) is True


def test_regenerating_every_profile_is_a_no_op_on_a_clean_tree():
    """The report generators call eval_graph for all 83 graphs. Before R1-04 that
    dirtied every profile.json with today's date."""
    import subprocess

    from agenticgraphs.registry import iter_graphs

    for gp in iter_graphs():
        evalcmd.eval_graph(load(gp)["name"])
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "graphs/*/*/profile.json"],
                           cwd=ROOT, capture_output=True, text=True).stdout
    assert dirty == "", dirty


# ------------------------------------------------------------------ D1-04 / R1-05


def test_a_guard_may_read_shards_processed_like_shards_failed():
    doc = _g(
        nodes=[{"id": "split", "speciality": "analyst", "abilities": ["analyze"],
                "outputs": ["shards"]},
               {"id": "work", "speciality": "worker", "abilities": ["execute_step"],
                "fan_out": {"over": "shards"}, "outputs": ["score"]},
               {"id": "done", "speciality": "judge", "abilities": ["adjudicate"]}],
        edges=[{"from": "split", "to": "work"}, {"from": "work", "to": "done"}],
        verification=[{"assert": "shards_processed >= 1"}],
    )
    assert not [e for e in lint_graph(doc) if "shards_processed" in e]


# ------------------------------------------------------------------ D4-02 / R1-06


def _two_graph_cycle(root):
    for cat, me, other in (("cat", "a", "b"), ("cat", "b", "a")):
        d = root / "graphs" / cat / me
        d.mkdir(parents=True)
        (d / "graph.yaml").write_text(yaml.safe_dump({
            "apiVersion": SPEC_VERSION, "name": me, "category": cat,
            "description": "cycle fixture",
            "nodes": [{"id": "phase", "speciality": "supervisor", "kind": "subgraph",
                       "ref": f"{cat}/{other}"}],
            "edges": [],
            "termination": {"max_steps": 5, "contract": "never"},
            "verification": [{"assert": "true"}],
        }, sort_keys=False))
    return load(root / "graphs" / "cat" / "a" / "graph.yaml")


def test_a_subgraph_cycle_fails_static_validation(tmp_path):
    """Only `expand()` at run time caught this; `agr validate` linted it clean."""
    errs = lint_graph(_two_graph_cycle(tmp_path), root=tmp_path)
    assert any("subgraph cycle" in e and "cat/a -> cat/b -> cat/a" in e for e in errs), errs


# ------------------------------------------------------------------ D4-04 / R1-07


def test_compose_by_reference_output_validates_and_carries_phase_scoped_checks():
    """The documented-preferred composition path emitted graphs that failed
    `agr validate` and pinned apiVersion to v1.1."""
    a = load(find_graph("invoice-reconciliation"))
    b = load(find_graph("competitive-intelligence"))
    doc = compose_by_reference(a, b)
    assert validate_schema(doc, "graph") == []
    assert lint_graph(doc) == []
    assert doc["apiVersion"] == SPEC_VERSION
    phases = {v["phase"] for v in doc["verification"]}
    assert phases == {"invoice-reconciliation", "competitive-intelligence"}


# ------------------------------------------------------------------ D1-05 / R1-10


def test_a_verifier_reachable_only_by_a_failure_edge_is_refused():
    doc = _g(
        nodes=[{"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
               {"id": "b", "speciality": "producer", "abilities": ["generate"]},
               {"id": "v", "speciality": "verifier", "kind": "verifier",
                "abilities": ["evaluate"], "criteria": "checks b",
                "outputs": ["ok: bool"]}],
        edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "v", "kind": "error"}],
        verification=[{"assert": "output.ok == true"}],
    )
    errs = lint_graph(doc)
    assert any("reachable only through error/compensate" in e for e in errs), errs


def test_no_registry_graph_relies_on_a_failure_only_verifier():
    from agenticgraphs.registry import iter_graphs

    for gp in iter_graphs():
        assert not [e for e in lint_graph(load(gp)) if "error/compensate" in e], gp


# ------------------------------------------------------------------ D7-01 / D8-01 / R1-08


def _run_asgi(app, headers):
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}
    asyncio.run(app(scope, receive, send))
    return sent


def test_bearer_guard_refuses_a_request_without_the_token():
    async def inner(scope, receive, send):
        raise AssertionError("inner app reached without a token")

    guarded = mcp_server.bearer_guard(inner, "s3cret")
    sent = _run_asgi(guarded, [])
    assert sent[0]["status"] == 401
    sent = _run_asgi(guarded, [(b"authorization", b"Bearer wrong")])
    assert sent[0]["status"] == 401


def test_bearer_guard_passes_the_right_token_through():
    reached = []

    async def inner(scope, receive, send):
        reached.append(scope["path"])

    guarded = mcp_server.bearer_guard(inner, "s3cret")
    _run_asgi(guarded, [(b"authorization", b"Bearer s3cret")])
    assert reached == ["/mcp"]


def test_http_refuses_to_start_autonomous_without_a_token(monkeypatch):
    monkeypatch.setenv("AGR_AUTONOMOUS", "1")
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)
    with pytest.raises(SystemExit, match=mcp_server.TOKEN_ENV):
        mcp_server.http_token()


def test_http_binds_loopback_on_both_sdk_layouts(monkeypatch):
    """The whole 'localhost only' story was a comment; now it is asserted (D8-01)."""
    monkeypatch.delenv("AGR_AUTONOMOUS", raising=False)
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)
    seen = {}

    class _Sdk2:
        def run(self, transport, host, port):
            seen["v2"] = (transport, host, port)

    class _Settings:
        host = port = None

    class _Sdk1:
        settings = _Settings()

        def run(self, transport):
            seen["v1"] = (transport, self.settings.host, self.settings.port)

    mcp_server.run_server(_Sdk2(), http=True, port=9999)
    mcp_server.run_server(_Sdk1(), http=True, port=9998)
    assert seen["v2"] == ("streamable-http", "127.0.0.1", 9999)
    assert seen["v1"] == ("streamable-http", "127.0.0.1", 9998)


def test_http_with_a_token_serves_the_guarded_app_on_loopback(monkeypatch):
    monkeypatch.delenv("AGR_AUTONOMOUS", raising=False)
    monkeypatch.setenv(mcp_server.TOKEN_ENV, "tok")
    served = {}

    class _Uvicorn:
        @staticmethod
        def run(app, host, port):
            served["host"], served["port"] = host, port

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", _Uvicorn)

    class _Sdk:
        def streamable_http_app(self):
            async def app(scope, receive, send):
                pass
            return app

    mcp_server.run_server(_Sdk(), http=True, port=9997)
    assert served == {"host": "127.0.0.1", "port": 9997}


# ------------------------------------------------------------------ D7-03 / R1-09


def test_infuse_preview_applies_the_lint_not_just_the_schema(monkeypatch):
    """Both branches of one tool must apply one gate. A schema-valid but
    lint-invalid mutation used to pass the preview branch."""
    pytest.importorskip("mcp", reason="mcp extra not installed")
    from agenticgraphs.mcp_server import create_server

    server = create_server()
    fn = server._tool_manager._tools["infuse_ability"].fn

    calls = []
    real = mcp_server.lint_graph

    def spy(doc, *a, **kw):
        calls.append(doc["name"])
        return real(doc, *a, **kw)

    monkeypatch.setattr(mcp_server, "lint_graph", spy)
    fn("code-review-pipeline", "triage", "web_search")
    assert calls == ["code-review-pipeline"]
