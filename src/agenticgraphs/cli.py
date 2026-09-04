"""agr — CLI for the agenticgraphs registry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .inspect import find_graph, render_profile, to_mermaid
from .registry import Registry, iter_graphs, iter_yaml, load
from .validate import validate_graph_file, validate_schema


def _need(name: str) -> dict:
    g = find_graph(name)
    if g is None:
        print(f"no graph named '{name}' (try: agr list)", file=sys.stderr)
        sys.exit(1)
    return load(g)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agr", description="evolvable, quality-proven agentic graphs")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list all graphs").add_argument(
        "--json", action="store_true", help="one JSON object per line: name, category, tier, motif")
    sub.add_parser("search", help="search graphs by term").add_argument("term")
    vp = sub.add_parser("validate", help="validate graph file(s), or all if none given")
    vp.add_argument("paths", nargs="*", type=Path)
    sub.add_parser("show", help="show a graph's full definition").add_argument("name")
    sub.add_parser("mermaid", help="emit a mermaid diagram for a graph").add_argument("name")
    sub.add_parser("profile", help="structural profile (deterministic; not a perf measurement)").add_argument("name")
    ep = sub.add_parser("eval", help="run golden cases, write profile.json (M1)")
    ep.add_argument("--resume-from", type=Path, metavar="JOURNAL",
                    help="resume a killed run from its journal (requires durability.resume)")
    ep.add_argument("--journal", type=Path, metavar="DIR",
                    help="write each case's journal to DIR/<case_id>.jsonl when the graph "
                         "declares durability.checkpoint: every_node (what --resume-from reads)")
    ep.add_argument("--no-replay", action="store_true",
                    help="ignore checked-in real-model recordings in the graph's live/ "
                         "and use mock fixtures instead")
    ep.add_argument("--run-commands", action="store_true",
                    help="actually execute verification[].command entries (runs real code "
                         "on this machine); default is to count and skip them")
    ep.add_argument("--auto-approve", action="store_true",
                    help="CI only: satisfy human approval gates automatically. Results are "
                         "stamped auto_approved and are not an authoritative sign-off.")
    ep.add_argument("name")
    ep.add_argument("--live", action="store_true",
                    help="use AGR_LLM_BASE_URL/AGR_LLM_MODEL instead of mock fixtures")
    ep.add_argument("--goal", metavar="TEXT",
                    help="what this run is about; overrides the goal in each case. "
                         "Graphs with goal.required refuse to run without one.")
    gp = sub.add_parser("goal", help="run one graph against a stated goal (v1.6)")
    gp.add_argument("name")
    gp.add_argument("goal", help="what this run is about, in plain language")
    gp.add_argument("--live", action="store_true",
                    help="use AGR_LLM_BASE_URL/AGR_LLM_MODEL instead of mock fixtures")
    gp.add_argument("--run-commands", action="store_true",
                    help="actually execute verification[].command entries")
    ip = sub.add_parser("infuse", help="add an ability to a node, gate-checked + lineage-logged (M2)")
    ip.add_argument("name")
    ip.add_argument("node")
    ip.add_argument("ability")
    op = sub.add_parser("optimize", help="v0 structural optimizer: dry-run by default (M2)")
    op.add_argument("name")
    op.add_argument("--apply", action="store_true")
    op.add_argument("--autonomous", action="store_true",
                    help="allow --apply to run unattended (also honors AGR_AUTONOMOUS=1); see docs/autonomy.md")
    ap = sub.add_parser("adapt", aliases=["instantiate"],
                        help="compile a graph to framework source (M3); `instantiate` is the MCP tool's name")
    ap.add_argument("name")
    ap.add_argument("--target", default="langgraph", choices=["langgraph", "crewai", "autogen"],
                    help="target framework: langgraph (default), crewai, or autogen")
    cp = sub.add_parser("compose", help="sequentially chain two graphs into one (M4)")
    cp.add_argument("graph_a", metavar="graph-a", help="graph run first")
    cp.add_argument("graph_b", metavar="graph-b", help="graph run after graph-a")
    cp.add_argument("-o", "--output", type=Path, help="write composed graph.yaml here instead of stdout")
    cp.add_argument("--name", help="name for the composed graph (default: '<a>-then-<b>')")
    cp.add_argument("--allow-gaps", action="store_true",
                    help="proceed even if graph-b needs blackboard keys graph-a doesn't appear to produce")
    cp.add_argument("--scaffold", type=Path, metavar="DIR",
                    help="write a registry-shaped bundle (graph.yaml, cases.yaml, usecase.yaml, "
                         "live/) to DIR so the composite can be evaluated and onboarded")
    cp.add_argument("--mode", choices=["inline", "subgraph"], default="inline",
                    help="inline: splice both graphs' nodes (v1). subgraph: emit a two-phase "
                         "parent that references each graph by ref (v1.1, edits to children propagate)")
    tp = sub.add_parser("triggers", help="compile a graph's declared triggers to a host artifact (M7)")
    tp.add_argument("name")
    tp.add_argument("--target", default="cron",
                    choices=["cron", "github-actions", "webhook"],
                    help="cron (default), github-actions, or a generic webhook filter")
    mp = sub.add_parser("mcp", help="serve the registry over MCP (stdio by default, or --http)")
    mp.add_argument("--http", action="store_true",
                     help="serve over HTTP/SSE instead of stdio (binds 127.0.0.1 only)")
    mp.add_argument("--port", type=int, default=8765, help="port for --http (default: 8765)")
    args = p.parse_args(argv)

    if args.cmd == "list":
        for e in Registry.load():
            if args.json:
                print(json.dumps({"name": e.name, "category": e.category, "tier": e.tier,
                                  "motif": e.motif, "description": e.description}))
            else:
                print(f"{e.category}/{e.name}: {e.description}")
        return 0
    if args.cmd == "search":
        # Now matches name + description + *category*, which is what the MCP
        # `search_graphs` tool has always matched. The two surfaces disagreed:
        # `agr search finance` returned nothing and exited 1 while the MCP tool
        # returned four graphs. One definition, and the wider one is the correct
        # one — a domain is a legitimate thing to search a registry by.
        hits = Registry.load().search(args.term)
        for e in hits:
            print(f"{e.category}/{e.name}: {e.description}")
        return 0 if hits else 1
    if args.cmd == "show":
        print(yaml.safe_dump(_need(args.name), sort_keys=False, width=120), end="")
        return 0
    if args.cmd == "mermaid":
        print(to_mermaid(_need(args.name)))
        return 0
    if args.cmd == "profile":
        print(render_profile(_need(args.name)))
        return 0
    if args.cmd == "eval":
        from .evalcmd import eval_graph
        profile = eval_graph(args.name, live=args.live, auto_approve=args.auto_approve,
                             run_commands=args.run_commands,
                             replay=not args.no_replay,
                             resume_from=args.resume_from,
                             goal=args.goal, journal_dir=args.journal)
        print(json.dumps(profile["measured"], indent=2))
        return 0 if profile["measured"]["pass_rate"] == 1.0 else 1
    if args.cmd == "goal":
        from .evalcmd import eval_graph
        doc = _need(args.name)
        profile = eval_graph(args.name, live=args.live, run_commands=args.run_commands,
                             replay=False, goal=args.goal)
        block = profile["measured"]
        declared = doc.get("goal") or {}
        print(f"goal:     {args.goal}")
        print(f"graph:    {doc['name']} ({doc['category']})")
        print(f"contract: {doc['termination'].get('contract', '—')}")
        if not declared:
            print("note:     this graph declares no goal block — the goal is seeded "
                  "on the blackboard but nothing requires it")
        print(json.dumps(block, indent=2))
        return 0 if block["pass_rate"] == 1.0 else 1
    if args.cmd == "infuse":
        from .mutate import infuse
        print(json.dumps(infuse(args.name, args.node, args.ability)))
        return 0
    if args.cmd == "optimize":
        from .autonomy import is_autonomous
        from .mutate import optimize
        autonomous = args.autonomous or is_autonomous()
        if args.apply and not autonomous:
            if sys.stdin.isatty():
                reply = input(f"apply optimizer changes to '{args.name}'? [y/N] ").strip().lower()
                if reply not in ("y", "yes"):
                    print("aborted (not applied)", file=sys.stderr)
                    return 1
            else:
                print(
                    "optimize --apply refused: no TTY and not autonomous. "
                    "Pass --autonomous (or set AGR_AUTONOMOUS=1) for unattended runs; "
                    "see docs/autonomy.md.",
                    file=sys.stderr,
                )
                return 1
        res = optimize(args.name, apply=args.apply)
        for note in res["notes"] or ["nothing to change"]:
            print(("applied: " if args.apply else "proposed: ") + note)
        return 0
    if args.cmd in ("adapt", "instantiate"):
        from .adapters import emit_autogen, emit_crewai, emit_langgraph
        emitters = {"langgraph": emit_langgraph, "crewai": emit_crewai, "autogen": emit_autogen}
        print(emitters[args.target](_need(args.name)))
        return 0
    if args.cmd == "compose":
        from .compose import ComposeError, compose, compose_by_reference

        try:
            if args.mode == "subgraph":
                doc = compose_by_reference(_need(args.graph_a), _need(args.graph_b),
                                           name=args.name)
                warnings: list[str] = []
            else:
                doc, warnings = compose(_need(args.graph_a), _need(args.graph_b),
                                        name=args.name, allow_gaps=args.allow_gaps)
        except ComposeError as e:
            print(f"compose failed: {e}", file=sys.stderr)
            print("(pass --allow-gaps to bypass a contract mismatch)", file=sys.stderr)
            return 1
        for w in warnings:
            print(w, file=sys.stderr)
        text = yaml.safe_dump(doc, sort_keys=False, width=120)
        if args.scaffold:
            from .compose import scaffold

            files = scaffold(doc, [_need(args.graph_a), _need(args.graph_b)], args.scaffold)
            print(f"scaffolded {args.scaffold}: " + ", ".join(str(f) for f in files))
            print("next: complete usecase.yaml, then `agr validate` and `agr eval` the bundle "
                  "from a registry root that contains it")
            return 0
        if args.output:
            args.output.write_text(text)
            print(f"wrote {args.output}")
        else:
            print(text, end="")
        return 0
    if args.cmd == "triggers":
        from .triggers import TriggerError, emit

        try:
            print(emit(_need(args.name), args.target), end="")
        except TriggerError as e:
            print(f"triggers: {e}", file=sys.stderr)
            return 1
        return 0
    if args.cmd == "mcp":
        from .mcp_server import main as serve

        try:
            serve(http=args.http, port=args.port)
        except ImportError as e:
            # The `mcp` package is imported lazily inside create_server(), so a bare
            # `uv sync` reaches here rather than failing at module import.
            print(f"mcp: the MCP server needs the `mcp` extra ({e}).\n"
                  "     install it with: uv sync --all-extras   "
                  "(or: pip install 'vitruvian-graphs[mcp]')", file=sys.stderr)
            return 2
        return 0
    if args.cmd == "validate":
        paths = args.paths or iter_graphs()
        failures = 0
        from .validate import lint_ability

        for kind, dirname in (("speciality", "specialities"), ("ability", "abilities")):
            for f in iter_yaml(dirname):
                adoc = load(f)
                errs = validate_schema(adoc, kind) or (lint_ability(adoc) if kind == "ability" else [])
                for err in errs:
                    print(f"FAIL {f.name}: {err}")
                failures += len(errs)
        # `gp`/`e` are the parser and except names elsewhere in this function;
        # reusing them here is what made mypy report reading a deleted variable.
        for graph_path in paths:
            errs = validate_graph_file(Path(graph_path))
            print(("OK  " if not errs else "FAIL") + f" {graph_path}")
            for err in errs:
                print(f"     {err}")
            failures += len(errs)
        return 1 if failures else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
