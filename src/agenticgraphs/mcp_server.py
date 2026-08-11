"""M3 MCP server: expose the registry to agents — search / get / instantiate / infuse.

Read-only over the registry by default: `infuse_ability` returns a mutated *copy*
(validated against the graph schema); persisting belongs to `agr infuse` on a
human-owned checkout. Set `AGR_AUTONOMOUS=1` (see agenticgraphs.autonomy /
docs/autonomy.md) to allow `infuse_ability(..., persist=True)` to write back,
gate-checked and committed to a dedicated `auto/mutations` branch.

Run with: `agr mcp` (stdio transport, default) or `agr mcp --http [--port 8765]`
(binds 127.0.0.1 only).
"""
from __future__ import annotations

import yaml

from .adapters import emit_langgraph
from .autonomy import AutonomyError
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
                goal = d.get("goal") or {}
                hits.append({"name": d["name"], "category": d["category"],
                             "description": d["description"],
                             # v1.6 — surfaced on the SEARCH result, not just on the
                             # graph, so a caller learns what it must bring before it
                             # spends a call on get_graph or instantiate.
                             "goal_required": bool(goal.get("required")),
                             "goal_description": goal.get("description", ""),
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
    def infuse_ability(name: str, node_id: str, ability: str, persist: bool = False) -> str:
        """Add `ability` to `node_id` in graph `name`.

        By default (persist=False) this returns a schema-validated copy of the
        graph without writing anything. With persist=True, the mutation is
        gate-checked (schema + MAST lint) and written back to the registry —
        but only when this process opted into unattended writes via
        AGR_AUTONOMOUS=1; see docs/autonomy.md. Execute-risk abilities are
        further capped behind AGR_AUTONOMOUS_ALLOW_EXECUTE=1.
        """
        if persist:
            from .mutate import infuse_autonomous

            try:
                result = infuse_autonomous(name, node_id, ability)
            except (AutonomyError, SystemExit) as e:
                raise ValueError(str(e)) from e
            return yaml.safe_dump(result, sort_keys=False)

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


def run_server(server, http: bool = False, port: int = 8765) -> None:
    """Run `server` over stdio (default) or HTTP/SSE bound to 127.0.0.1 only."""
    if not http:
        server.run()
        return
    try:
        # mcp SDK >= 2.0: MCPServer.run(transport=..., **kwargs)
        server.run(transport="streamable-http", host="127.0.0.1", port=port)
    except TypeError:
        # mcp SDK 1.x FastMCP: host/port live on .settings
        server.settings.host = "127.0.0.1"
        server.settings.port = port
        server.run(transport="streamable-http")


def main(http: bool = False, port: int = 8765) -> None:
    run_server(create_server(), http=http, port=port)
