import ast

import pytest

from agenticgraphs.adapters import emit_autogen, emit_crewai, emit_langgraph
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import iter_graphs, load


def test_every_graph_compiles_to_valid_langgraph_source():
    for g in iter_graphs():
        doc = load(g)
        src = emit_langgraph(doc)
        ast.parse(src)  # syntactically valid Python
        for n in doc["nodes"]:
            assert f'g.add_node("{n["id"]}"' in src
        assert "app = g.compile()" in src
        assert "NotImplementedError" in src  # honest: behavior must be bound


def test_router_emits_first_match_semantics():
    src = emit_langgraph(load(find_graph("cost-routed-research")))
    assert "hits[0] if hits else END" in src


@pytest.mark.parametrize("name", ["cost-routed-research", "verifier-swarm"])
def test_crewai_target_compiles(name):
    doc = load(find_graph(name))
    src = emit_crewai(doc)
    compile(src, f"<{name}-crewai>", "exec")  # runnable-shaped: no syntax errors
    assert "from crewai import Agent, Crew, Process, Task" in src
    for n in doc["nodes"]:
        assert f'role="{n["speciality"]}"' in src
        assert f"agent={n['id'].replace('-', '_')}" in src.replace("node_", "")
    assert "process=Process.sequential" in src
    assert doc.get("termination", {}).get("contract") in src


def test_crewai_terminal_task_gets_contract_as_expected_output():
    doc = load(find_graph("cost-routed-research"))
    src = emit_crewai(doc)
    has_out = {e["from"] for e in doc["edges"]}
    terminals = [n["id"] for n in doc["nodes"] if n["id"] not in has_out]
    assert terminals, "graph must have a terminal node for this assertion to be meaningful"
    for t in terminals:
        var = "node_" + t.replace("-", "_")
        idx = src.index(f"{var}_task = Task(")
        chunk = src[idx: idx + 400]
        assert doc["termination"]["contract"] in chunk


@pytest.mark.parametrize("name", ["cost-routed-research", "verifier-swarm"])
def test_autogen_target_compiles(name):
    doc = load(find_graph(name))
    src = emit_autogen(doc)
    compile(src, f"<{name}-autogen>", "exec")  # runnable-shaped: no syntax errors
    assert "from autogen import AssistantAgent, ConversableAgent, GroupChat, GroupChatManager" in src
    assert "def is_termination_msg(msg: dict) -> bool:" in src
    assert "def _select_speaker(last_speaker, groupchat):" in src
    for n in doc["nodes"]:
        assert f'name="{n["id"]}"' in src
    assert "GroupChatManager(groupchat=groupchat)" in src


def test_autogen_router_encodes_edge_conditions():
    doc = load(find_graph("cost-routed-research"))
    src = emit_autogen(doc)
    conditional = [e for e in doc["edges"] if e.get("when")]
    assert conditional, "expected at least one conditional edge on this router graph"
    for e in conditional:
        assert repr(e["when"]) in src


def test_mcp_tools_registered():
    pytest.importorskip("mcp")
    import asyncio

    from agenticgraphs.mcp_server import create_server

    tools = asyncio.run(create_server().list_tools())
    assert {t.name for t in tools} == {"search_graphs", "get_graph", "instantiate", "infuse_ability"}
