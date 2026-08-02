"""M3 MCP server: expose the registry to agents — search / get / instantiate / infuse.

Read-only over the registry: `infuse_ability` returns a mutated *copy* (validated
against the graph schema); persisting belongs to `agr infuse` on a human-owned checkout.
Run with: `agr mcp` (stdio transport).
"""
from __future__ import annotations

import yaml

from .adapters import emit_langgraph
from .inspect import find_graph, structural_profile
from .registry import iter_graphs, iter_yaml, load
from .validate import validate_schema


def create_server():
    try:  # mcp SDK 1.x
        from mcp.server.fastmcp import FastMCP as _Server
    except ImportError:  # mcp SDK >= 2.0
        from mcp.server.mcpserver import MCPServer as _Server

    mcp = _Server("agenticgraphs")

    @mcp.tool()
    def search_graphs(term: str) -> list[dict]:
        """Search the graph registry by keyword; returns name/category/description/profile."""
        hits = []
        for g in iter_graphs():
            d = load(g)
            if term.lower() in (d["name"] + " " + d["description"] + " " + d["category"]).lower():
                hits.append({"name": d["name"], "category": d["category"],
                             "description": d["description"],
                             "structural": structural_profile(d)["structural"]})
        return hits

    @mcp.tool()
    def get_graph(name: str) -> str:
        """Full AGR YAML definition of a graph."""
        g = find_graph(name)
        if g is None:
            raise ValueError(f"no graph named '{name}'")
        return g.read_text()

    @mcp.tool()
    def instantiate(name: str, target: str = "langgraph") -> str:
        """Compile a graph to runnable framework source (targets: langgraph)."""
        if target != "langgraph":
            raise ValueError("only target='langgraph' is implemented (M3)")
        g = find_graph(name)
        if g is None:
            raise ValueError(f"no graph named '{name}'")
        return emit_langgraph(load(g))

    @mcp.tool()
    def infuse_ability(name: str, node_id: str, ability: str) -> str:
        """Return a schema-validated copy of the graph with `ability` added to `node_id`."""
        g = find_graph(name)
        if g is None:
            raise ValueError(f"no graph named '{name}'")
        if ability not in {load(p)["name"] for p in iter_yaml("abilities")}:
            raise ValueError(f"unknown ability '{ability}'")
        doc = load(g)
        node = next((n for n in doc["nodes"] if n["id"] == node_id), None)
        if node is None:
            raise ValueError(f"no node '{node_id}' in '{name}'")
        if ability not in node.setdefault("abilities", []):
            node["abilities"].append(ability)
        errs = validate_schema(doc, "graph")
        if errs:
            raise ValueError("mutation violates schema: " + "; ".join(errs))
        return yaml.safe_dump(doc, sort_keys=False)

    return mcp


def main() -> None:
    create_server().run()
