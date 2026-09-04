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
