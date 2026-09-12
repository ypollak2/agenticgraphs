"""The MCP surface, which is how an *agent* reaches this registry.

At 42% this was the least-covered module in the package while being the one
exposed to callers the maintainer never sees. `create_server` needs the mcp SDK;
the tool bodies do not, so they are exercised through the registered functions.
"""
from __future__ import annotations

import pytest
import yaml

mcp = pytest.importorskip("mcp", reason="mcp extra not installed")

from agenticgraphs.mcp_server import create_server  # noqa: E402


@pytest.fixture(scope="module")
def tools():
    server = create_server()
    fns = getattr(server, "_tool_manager", None)
    if fns is not None:  # mcp SDK 1.x FastMCP
        return {name: t.fn for name, t in fns._tools.items()}
    pytest.skip("unrecognised mcp SDK layout")


def test_search_returns_the_goal_a_caller_must_bring(tools):
    """v1.6 surfaced this on search so an agent learns the requirement before
    spending a call on get_graph. Every graph declares one as of v1.8."""
    hits = tools["search_graphs"]("incident")
    assert hits
    for h in hits:
        assert h["goal_required"] is True
        assert h["goal_description"]


def test_get_graph_returns_parseable_agr(tools):
    doc = yaml.safe_load(tools["get_graph"]("code-review-pipeline"))
    assert doc["name"] == "code-review-pipeline"
    assert doc["apiVersion"].startswith("agr/")


def test_get_graph_rejects_an_unknown_name(tools):
    with pytest.raises(ValueError, match="no graph"):
        tools["get_graph"]("no-such-graph")


def test_instantiate_serves_every_adapter_target(tools):
    """Pinned to langgraph '(M3)' two milestones after crewai/autogen shipped (D5-06)."""
    assert "StateGraph" in tools["instantiate"]("code-review-pipeline")
    assert "Crew(" in tools["instantiate"]("code-review-pipeline", target="crewai")
    assert "GroupChat(" in tools["instantiate"]("code-review-pipeline", target="autogen")
    with pytest.raises(ValueError, match="unknown target"):
        tools["instantiate"]("code-review-pipeline", target="dagster")


def test_infuse_without_persist_mutates_a_copy_only(tools):
    from agenticgraphs.inspect import find_graph

    before = find_graph("code-review-pipeline").read_text()
    out = yaml.safe_load(tools["infuse_ability"]("code-review-pipeline", "triage", "web_search"))
    node = next(n for n in out["nodes"] if n["id"] == "triage")
    assert "web_search" in node["abilities"]
    assert find_graph("code-review-pipeline").read_text() == before, "persist=False wrote to disk"


def test_infuse_rejects_unknown_ability_and_node(tools):
    with pytest.raises(ValueError, match="unknown ability"):
        tools["infuse_ability"]("code-review-pipeline", "triage", "teleport")
    with pytest.raises(ValueError, match="no node"):
        tools["infuse_ability"]("code-review-pipeline", "nope", "web_search")


def test_persist_is_refused_without_the_autonomy_opt_in(tools, monkeypatch):
    """The default posture is a human-owned checkout. Over MCP that matters more,
    not less: the caller is an agent nobody is watching."""
    monkeypatch.delenv("AGR_AUTONOMOUS", raising=False)
    with pytest.raises(ValueError, match="AGR_AUTONOMOUS"):
        tools["infuse_ability"]("code-review-pipeline", "triage", "web_search", persist=True)


# ---------------------------------------------------------- 2026-09-12 audit, A1


def test_server_info_reports_the_revision_it_serves(tools):
    """A long-lived daemon is not a current one.

    The LaunchAgent sets `KeepAlive: true`, so the process survives every merge.
    The audit found one serving a 34-day-old checkout — six tools shipped five
    weeks earlier were unreachable while `tools/list` answered happily. Nothing
    in the protocol let a caller notice, so the server now says what it is.
    """
    info = tools["server_info"]()
    assert info["revision"], "a caller must be able to compare this against HEAD"
    assert info["spec_version"].startswith("agr/v")
    assert info["graphs"] == 83
    assert isinstance(info["dirty"], bool)
    assert info["uptime_seconds"] >= 0
    assert info["transport_authenticated"] is False  # no AGR_MCP_TOKEN under pytest
    assert info["autonomous"] is False


def test_server_info_never_raises_when_git_is_unavailable(monkeypatch, tmp_path):
    """A server must not fail to describe itself because git is missing."""
    import subprocess

    from agenticgraphs import mcp_server

    def boom(*a, **kw):
        assert kw.get("timeout"), "subprocess.run called without a timeout"
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    assert mcp_server.served_revision(tmp_path) == {"revision": "unknown", "dirty": False}


def test_server_info_reports_unknown_outside_a_git_checkout(tmp_path):
    from agenticgraphs.mcp_server import served_revision

    assert served_revision(tmp_path) == {"revision": "unknown", "dirty": False}


# ---------------------------------------------------------- 2026-09-12 audit, C13


def test_the_installer_ships_a_token_and_supervises_the_server_itself():
    """Two failures the plist caused, both invisible until they were looked for.

    It carried no `EnvironmentVariables`, so `AGR_MCP_TOKEN` was unset:
    `bearer_guard` was never installed **and** `run_graph(live=True)` — which
    refuses to spend on an endpoint for an unauthenticated caller — was
    permanently unreachable. One absent variable turned off the guard and the
    feature it guards.

    And it launched the server through `uv run`, which forks a child python.
    `launchctl kickstart -k` killed the `uv` parent and left the child orphaned
    to pid 1, deaf to SIGTERM. One was found alive from 9 Aug, five weeks and a
    merge behind, while a restart reported success.
    """
    from pathlib import Path

    script = (Path(__file__).resolve().parents[1] / "scripts" / "install_service.sh").read_text()

    assert "AGR_MCP_TOKEN" in script and "EnvironmentVariables" in script
    assert "openssl rand -hex 32" in script, "a token must be minted, not left to the operator"
    assert 'chmod 600 "$PLIST_PATH"' in script, "the plist holds the token"
    assert "--no-token" in script, "the old posture must stay reachable, deliberately"

    argv = script.split("<key>ProgramArguments</key>", 1)[1].split("</array>", 1)[0]
    assert "${AGR_BIN}" in argv, "launchd must exec the server, not a launcher"
    assert "<string>run</string>" not in argv, "`uv run` reintroduces the orphan"
    assert "plist_is_direct" in script, "--restart must refuse a plist that orphans"
