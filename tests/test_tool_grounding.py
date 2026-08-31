"""Bound abilities: the difference between a claim and evidence.

`ToolRunner` and `bindings` are what make an assert *grounded* — held because a
command exited 0 rather than because a model said so. Both were among the least
covered modules in the package, which is the wrong place for that.
"""
from __future__ import annotations

import json
import subprocess
from io import BytesIO

import pytest

from agenticgraphs import bindings, harness
from agenticgraphs.bindings import ToolCall, available, bind_for, invoke

# --------------------------------------------------------------------- bindings

def test_mutating_abilities_stay_unbound_without_the_opt_in():
    """Risk lives in `abilities/*.yaml` and has since M0; this reads that
    declaration rather than inventing a second permission model."""
    assert "run_command" not in available()
    assert "run_command" in available(allow_mutating=True)
    assert "read_diff" in available(), "read-risk abilities need no opt-in"


def test_a_node_is_offered_only_what_it_declares():
    node = {"id": "n", "abilities": ["read_diff"]}
    assert set(bind_for(node)) == {"read_diff"}
    assert set(bind_for({"id": "n", "abilities": []})) == set()


def test_invoking_an_unbound_ability_is_refused(tmp_path):
    """`invoke` records the refusal rather than raising: an ability that was not
    allowed to run is a fact about the run, and a trace that only exists for
    successful calls is not a trace."""
    rec = invoke("run_command", {"command": "echo hi"}, cwd=tmp_path, allow_mutating=False)
    assert not rec.ok and "not bound" in rec.detail


def test_run_command_reports_the_exit_code_as_the_fact(tmp_path):
    rec = invoke("run_command", {"command": "sh -c 'exit 3'"}, cwd=tmp_path, allow_mutating=True)
    assert isinstance(rec, ToolCall)
    assert rec.evidence["exit_code"] == 3


def test_run_command_needs_a_command(tmp_path):
    rec = invoke("run_command", {}, cwd=tmp_path, allow_mutating=True)
    assert not rec.ok and "needs a 'command'" in rec.detail


def test_read_diff_returns_real_file_and_line_pairs(tmp_path):
    """The asserts want `f.file and f.line`; this is where those come from."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    rec = invoke("read_diff", {"ref": "HEAD"}, cwd=tmp_path)
    assert rec.evidence["files"] == ["a.py"]
    assert all(h["file"] and h["line"] for h in rec.evidence["hunks"])


def test_web_search_returns_no_result_rather_than_an_invented_one(monkeypatch, tmp_path):
    """A `source_url` failing because nothing was fetched is a truthful result;
    a plausible-looking invented URL is the failure this module exists to stop."""
    def boom(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(bindings.urllib.request, "urlopen", boom)
    rec = invoke("web_search", {"query": "anything"}, cwd=tmp_path)
    assert rec.evidence["results"] == []
    assert "OSError" in rec.evidence["error"]


def test_web_search_extracts_reachable_urls(monkeypatch, tmp_path):
    html = b'<a href="https://duckduckgo.com/x">skip</a><a href="https://example.org/a">a</a>'

    class _R:
        def read(self, _n):
            return html

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(bindings.urllib.request, "urlopen", lambda *a, **k: _R())
    rec = invoke("web_search", {"query": "q"}, cwd=tmp_path)
    urls = [r["source_url"] for r in rec.evidence["results"]]
    assert urls == ["https://example.org/a"], "the search engine's own links are not results"


def test_web_search_needs_a_query(tmp_path):
    rec = invoke("web_search", {}, cwd=tmp_path)
    assert not rec.ok and "needs a 'query'" in rec.detail


# ------------------------------------------------------------------- ToolRunner

def _msg(content=None, tool_calls=None):
    return BytesIO(json.dumps({
        "choices": [{"message": {"content": content, "tool_calls": tool_calls}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }).encode())


class _Ctx:
    def __init__(self, b):
        self.b = b

    def __enter__(self):
        return self.b

    def __exit__(self, *a):
        return False


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AGR_LLM_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("AGR_LLM_MODEL", "gpt-4o")
    monkeypatch.setattr(harness.time, "sleep", lambda _: None)


def test_registry_root_is_separate_from_the_command_working_directory(env, tmp_path):
    """Pointing the runner at a target repo must not unbind its abilities."""
    r = harness.ToolRunner(root=tmp_path)
    assert r.root == tmp_path
    assert set(bind_for({"id": "n", "abilities": ["read_diff"]},
                        root=r.registry_root)) == {"read_diff"}


def test_a_node_with_no_bound_ability_behaves_like_the_plain_runner(env, monkeypatch):
    monkeypatch.setattr(harness.urllib.request, "urlopen",
                        lambda *a, **k: _Ctx(_msg('{"ok": true}')))
    r = harness.ToolRunner()
    r.bind({"termination": {}, "verification": []})
    assert r.run({"id": "n", "speciality": "producer", "abilities": [], "outputs": ["ok"]},
                 {}) == {"ok": True}


def test_a_tool_call_is_executed_and_recorded_as_evidence(env, monkeypatch, tmp_path):
    script = [
        _msg(tool_calls=[{"id": "c1", "function": {"name": "read_diff", "arguments": "{}"}}]),
        _msg('{"findings": []}'),
    ]
    monkeypatch.setattr(harness.urllib.request, "urlopen",
                        lambda *a, **k: _Ctx(script.pop(0)))
    rep = harness.RunReport()
    r = harness.ToolRunner(root=tmp_path, report=rep)
    r.bind({"termination": {}, "verification": []})
    out = r.run({"id": "n", "speciality": "analyst", "abilities": ["read_diff"],
                 "outputs": ["findings"]}, {})
    assert out == {"findings": []}
    assert [c.ability for c in rep.tool_calls] == ["read_diff"], \
        "a trace that only exists for successful calls is not a trace"


def test_malformed_tool_arguments_do_not_abort_the_run(env, monkeypatch, tmp_path):
    script = [
        _msg(tool_calls=[{"id": "c1", "function": {"name": "read_diff",
                                                   "arguments": "{not json"}}]),
        _msg('{"findings": []}'),
    ]
    monkeypatch.setattr(harness.urllib.request, "urlopen",
                        lambda *a, **k: _Ctx(script.pop(0)))
    r = harness.ToolRunner(root=tmp_path, report=harness.RunReport())
    r.bind({"termination": {}, "verification": []})
    assert r.run({"id": "n", "speciality": "analyst", "abilities": ["read_diff"],
                  "outputs": ["findings"]}, {}) == {"findings": []}


def test_a_model_that_never_stops_calling_tools_is_asked_once_without_them(env, monkeypatch,
                                                                          tmp_path):
    """`MAX_TOOL_ROUNDS` is a bound, so the run must still produce an object."""
    call = _msg(tool_calls=[{"id": "c", "function": {"name": "read_diff", "arguments": "{}"}}])
    n = {"i": 0}

    def urlopen(*a, **k):
        n["i"] += 1
        if n["i"] <= harness.ToolRunner.MAX_TOOL_ROUNDS:
            return _Ctx(_msg(tool_calls=[{"id": f"c{n['i']}",
                                          "function": {"name": "read_diff",
                                                       "arguments": "{}"}}]))
        return _Ctx(_msg('{"findings": ["final"]}'))

    monkeypatch.setattr(harness.urllib.request, "urlopen", urlopen)
    r = harness.ToolRunner(root=tmp_path, report=harness.RunReport())
    r.bind({"termination": {}, "verification": []})
    assert r.run({"id": "n", "speciality": "analyst", "abilities": ["read_diff"],
                  "outputs": ["findings"]}, {}) == {"findings": ["final"]}
    assert n["i"] == harness.ToolRunner.MAX_TOOL_ROUNDS + 1
    assert call is not None
