"""agr — CLI for the agenticgraphs registry."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .registry import ROOT, iter_graphs, iter_yaml, load
from .validate import validate_graph_file


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agr", description="evolvable, quality-proven agentic graphs")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list all graphs")
    sp = sub.add_parser("search", help="search graphs by term")
    sp.add_argument("term")
    vp = sub.add_parser("validate", help="validate graph file(s), or all if none given")
    vp.add_argument("paths", nargs="*", type=Path)
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
    if args.cmd == "validate":
        paths = args.paths or iter_graphs()
        # speciality/ability files are schema-checked too
        from .validate import validate_schema
        failures = 0
        for kind, dirname in (("speciality", "specialities"), ("ability", "abilities")):
            for f in iter_yaml(dirname):
                errs = validate_schema(load(f), kind)
                for e in errs:
                    print(f"FAIL {f.name}: {e}")
                failures += len(errs)
        for gp in paths:
            errs = validate_graph_file(Path(gp))
            status = "OK  " if not errs else "FAIL"
            print(f"{status} {gp}")
            for e in errs:
                print(f"     {e}")
            failures += len(errs)
        return 1 if failures else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
