"""agr — CLI for the agenticgraphs registry."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from .inspect import find_graph, render_profile, to_mermaid
from .registry import iter_graphs, iter_yaml, load
from .validate import validate_graph_file, validate_schema


def _need(name: str):
    g = find_graph(name)
    if g is None:
        print(f"no graph named '{name}' (try: agr list)", file=sys.stderr)
        sys.exit(1)
    return load(g)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agr", description="evolvable, quality-proven agentic graphs")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list all graphs")
    sub.add_parser("search", help="search graphs by term").add_argument("term")
    vp = sub.add_parser("validate", help="validate graph file(s), or all if none given")
    vp.add_argument("paths", nargs="*", type=Path)
    sub.add_parser("show", help="show a graph's full definition").add_argument("name")
    sub.add_parser("mermaid", help="emit a mermaid diagram for a graph").add_argument("name")
    sub.add_parser("profile", help="structural profile (deterministic; not a perf measurement)").add_argument("name")
    args = p.parse_args(argv)

    if args.cmd == "list":
        for g in iter_graphs():
            d = load(g)
            print(f"{d['category']}/{d['name']}: {d['description']}")
        return 0
    if args.cmd == "search":
        hits = [load(g) for g in iter_graphs()]
        hits = [d for d in hits if args.term.lower() in (d["name"] + d["description"]).lower()]
        for d in hits:
            print(f"{d['category']}/{d['name']}: {d['description']}")
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
    if args.cmd == "validate":
        paths = args.paths or iter_graphs()
        failures = 0
        for kind, dirname in (("speciality", "specialities"), ("ability", "abilities")):
            for f in iter_yaml(dirname):
                errs = validate_schema(load(f), kind)
                for e in errs:
                    print(f"FAIL {f.name}: {e}")
                failures += len(errs)
        for gp in paths:
            errs = validate_graph_file(Path(gp))
            print(("OK  " if not errs else "FAIL") + f" {gp}")
            for e in errs:
                print(f"     {e}")
            failures += len(errs)
        return 1 if failures else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
