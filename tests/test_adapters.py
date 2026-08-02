import ast

import pytest

from agenticgraphs.adapters import emit_langgraph
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


def test_mcp_tools_registered():
    pytest.importorskip("mcp")
    import asyncio

    from agenticgraphs.mcp_server import create_server

    tools = asyncio.run(create_server().list_tools())
    assert {t.name for t in tools} == {"search_graphs", "get_graph", "instantiate", "infuse_ability"}
