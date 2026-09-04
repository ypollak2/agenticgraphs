"""M3 MCP server: expose the registry to agents — search / get / instantiate / infuse.

Read-only over the registry by default: `infuse_ability` returns a mutated *copy*
(validated against the graph schema); persisting belongs to `agr infuse` on a
human-owned checkout. Set `AGR_AUTONOMOUS=1` (see agenticgraphs.autonomy /
docs/autonomy.md) to allow `infuse_ability(..., persist=True)` to write back,
gate-checked and committed to a dedicated `auto/mutations` branch.

Run with: `agr mcp` (stdio transport, default) or `agr mcp --http [--port 8765]`
(binds 127.0.0.1 only). Over HTTP, set `AGR_MCP_TOKEN` to require a bearer token
on every request; it is mandatory when `AGR_AUTONOMOUS=1`, because loopback alone
does not distinguish the intended caller from any other local process.
"""
from __future__ import annotations

import hmac
import json
import os
import sys

import yaml

from .adapters import emit_autogen, emit_crewai, emit_langgraph
from .autonomy import AutonomyError, is_autonomous
from .inspect import find_graph
from .registry import Registry, iter_yaml, load
from .validate import lint_graph, validate_schema

TOKEN_ENV = "AGR_MCP_TOKEN"  # noqa: S105 — the env var NAME, not a secret

NO_TOKEN_WHILE_AUTONOMOUS_MSG = (
    f"agr mcp --http refused: AGR_AUTONOMOUS=1 is set but {TOKEN_ENV} is not. "
    "Binding to 127.0.0.1 does not stop another local process from calling "
    "infuse_ability(persist=true); set a token so only the intended caller can. "
    "See docs/autonomy.md."
)


def create_server():
    try:  # mcp SDK 1.x
        from mcp.server.fastmcp import FastMCP as _Server
    except ImportError:  # mcp SDK >= 2.0
        from mcp.server.mcpserver import MCPServer as _Server

    mcp = _Server("agenticgraphs")

    @mcp.tool()
    def search_graphs(term: str) -> list[dict]:
        """Search the graph registry by keyword; returns name/category/description/profile."""
        return [
            {"name": e.name, "category": e.category, "description": e.description,
             # v1.6 — surfaced on the SEARCH result, not just on the graph, so a
             # caller learns what it must bring before it spends a call on
             # get_graph or instantiate.
             "goal_required": e.goal_required,
             "goal_description": e.goal_description,
             "tier": e.tier,
             "structural": e.structural}
            for e in Registry.load().search(term)
        ]

    @mcp.tool()
    def get_graph(name: str) -> str:
        """Full AGR YAML definition of a graph."""
        g = find_graph(name)
        if g is None:
            raise ValueError(f"no graph named '{name}'")
        return g.read_text()

    @mcp.tool()
    def instantiate(name: str, target: str = "langgraph") -> str:
        """Compile a graph to runnable framework source.

        targets: langgraph (default), crewai, autogen — the same three
        `agr adapt --target` serves. The tool was pinned to langgraph with an
        '(M3)' note two milestones after the others shipped (2026-09-04 audit,
        D5-06).
        """
        emitters = {"langgraph": emit_langgraph, "crewai": emit_crewai, "autogen": emit_autogen}
        if target not in emitters:
            raise ValueError(f"unknown target '{target}'; choose from {sorted(emitters)}")
        g = find_graph(name)
        if g is None:
            raise ValueError(f"no graph named '{name}'")
        return emitters[target](load(g))

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
        # Same gate as the persist=True path (schema *and* lint). The preview
        # branch used to run schema only, so the two branches of one tool applied
        # different checks to the same mutation (2026-09-04 audit, D7-03).
        errs = validate_schema(doc, "graph") or lint_graph(doc)
        if errs:
            raise ValueError("mutation violates schema/lint: " + "; ".join(errs))
        return yaml.safe_dump(doc, sort_keys=False)

    # ---- R6-01: what the CLI could do and the MCP surface could not ----

    @mcp.tool()
    def validate_graph(graph_yaml: str) -> list[str]:
        """Schema + lint a candidate AGR graph (YAML text). Empty list means valid."""
        doc = yaml.safe_load(graph_yaml)
        if not isinstance(doc, dict):
            return ["not a mapping"]
        return validate_schema(doc, "graph") or lint_graph(doc)

    @mcp.tool()
    def run_graph(name: str, goal: str = "", inputs: dict | None = None,
                  live: bool = False, run_commands: bool = False) -> dict:
        """Run a graph's golden cases and return the measured block.

        Mock fixtures by default (mechanics, not model quality). `live=True`
        uses AGR_LLM_BASE_URL/AGR_LLM_MODEL and requires AGR_MCP_TOKEN to be set,
        so an unauthenticated loopback caller cannot spend on the endpoint.
        `run_commands=True` executes verification[].command entries and requires
        AGR_AUTONOMOUS_ALLOW_EXECUTE=1, the same cap as an execute-risk persist.
        Nothing is written to the registry.
        """
        from .autonomy import execute_allowed
        from .evalcmd import eval_graph

        if live and not os.environ.get(TOKEN_ENV):
            raise ValueError(f"live runs over MCP require {TOKEN_ENV} to be set")
        if run_commands and not execute_allowed():
            raise ValueError("run_commands over MCP requires AGR_AUTONOMOUS_ALLOW_EXECUTE=1")
        if find_graph(name) is None:
            raise ValueError(f"no graph named '{name}'")
        profile = eval_graph(name, live=live, run_commands=run_commands, goal=goal or None,
                             write=False, replay=not live)
        block = dict(profile["measured"])
        if inputs:
            block["note"] = "inputs are supplied by the graph's golden cases; use `goal` to set the subject"
        return block

    @mcp.tool()
    def list_abilities() -> list[dict]:
        """Every ability with its risk, idempotency and whether this runtime binds it."""
        from .bindings import BindingError, resolve_binding

        rows = []
        for p in iter_yaml("abilities"):
            adoc = load(p)
            try:
                bound = resolve_binding(adoc) is not None if adoc.get("binding") else False
            except BindingError:
                bound = False
            rows.append({"name": adoc["name"], "risk": adoc.get("risk", "read"),
                         "idempotent": adoc.get("idempotent", True), "bound": bound,
                         "description": adoc["description"]})
        return rows

    @mcp.tool()
    def list_specialities() -> list[dict]:
        """Every speciality with the abilities it requires and may optionally hold."""
        return [{"name": d["name"], "requires": d["requires_abilities"],
                 "optional": d.get("optional_abilities", []), "description": d["description"]}
                for d in (load(p) for p in iter_yaml("specialities"))]

    @mcp.tool()
    def get_profile(name: str) -> dict:
        """The graph's profile.json: structural facts, mock and live evidence, tier."""
        g = find_graph(name)
        if g is None:
            raise ValueError(f"no graph named '{name}'")
        pf = g.parent / "profile.json"
        return json.loads(pf.read_text()) if pf.exists() else {"error": "no profile yet; run agr eval"}

    @mcp.tool()
    def diff_graphs(a: str, b: str) -> str:
        """Unified diff of two registry graphs' YAML, `a` -> `b`."""
        import difflib

        ga, gb = find_graph(a), find_graph(b)
        if ga is None or gb is None:
            raise ValueError(f"no graph named '{a if ga is None else b}'")
        return "".join(difflib.unified_diff(
            ga.read_text().splitlines(True), gb.read_text().splitlines(True),
            fromfile=f"{a}/graph.yaml", tofile=f"{b}/graph.yaml"))

    return mcp


def bearer_guard(app, token: str):
    """Wrap an ASGI app so every HTTP request must carry `Authorization: Bearer <token>`.

    Constant-time comparison; anything else is answered 401 before the MCP app
    sees the request. Non-HTTP scopes (lifespan) pass through untouched.
    """
    expected = token.encode()

    async def guarded(scope, receive, send):
        if scope.get("type") != "http":
            await app(scope, receive, send)
            return
        header = next((v for k, v in scope.get("headers", []) if k == b"authorization"), b"")
        ok = header.startswith(b"Bearer ") and hmac.compare_digest(header[7:], expected)
        if not ok:
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"text/plain"),
                                    (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": b"unauthorized\n"})
            return
        await app(scope, receive, send)

    return guarded


def http_token() -> str | None:
    """The token HTTP callers must present, or None. Refuses to run autonomous without one."""
    token = os.environ.get(TOKEN_ENV) or None
    if is_autonomous() and not token:
        raise SystemExit(NO_TOKEN_WHILE_AUTONOMOUS_MSG)
    return token


def run_server(server, http: bool = False, port: int = 8765) -> None:
    """Run `server` over stdio (default) or HTTP bound to 127.0.0.1 only.

    With `AGR_MCP_TOKEN` set the HTTP transport is wrapped in `bearer_guard`
    (2026-09-04 audit, D7-01). Without it, and without AGR_AUTONOMOUS, the
    server stays read-only over the registry, which is the pre-existing posture.
    """
    if not http:
        server.run()
        return
    token = http_token()
    if token:
        import uvicorn

        app = bearer_guard(server.streamable_http_app(), token)
        uvicorn.run(app, host="127.0.0.1", port=port)
        return
    print(f"agr mcp --http: no {TOKEN_ENV} set; any local process can reach this server "
          "(read-only unless AGR_AUTONOMOUS=1, which then requires a token).",
          file=sys.stderr)
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
