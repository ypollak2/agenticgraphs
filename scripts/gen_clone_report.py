"""Count how many graphs are the same graph.

A registry's headline number is how many graphs it has. That number only means
something if the graphs differ. This strips the four strings that are free to
change — name, description, category, and the identifiers inside asserts — and
reports what is left, so "83 graphs" cannot quietly mean "40 shapes relabelled".

`criteria` counts. It is the field where domain knowledge lives (agr/v1.8), so
two graphs with one topology and different rubrics are two graphs; two with one
topology and no rubric were never more than one.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import ROOT, iter_graphs, load

_FREE = ("name", "description", "category")


def _skeleton(doc: dict, *, with_criteria: bool) -> str:
    """Everything that is not free to differ, canonicalised."""
    d = json.loads(json.dumps({k: v for k, v in doc.items() if k not in _FREE}))
    for v in d.get("verification") or []:
        # Identifier names inside an assert are as renameable as the graph's own
        # name; the SHAPE of the check is what distinguishes two contracts.
        if "assert" in v:
            v["assert"] = re.sub(r"[A-Za-z_][A-Za-z_0-9]*", "_", v["assert"])
        v.pop("describe", None)
    d.get("termination", {}).pop("contract", None)
    # `goal.description` is prose, as free to differ as `description` itself.
    # Counting it would let a registry of identical graphs look distinct because
    # each one was given a different sentence.
    d.get("goal", {}).pop("description", None)
    for n in d["nodes"]:
        n["outputs"] = ["_" for _ in (n.get("outputs") or [])] or None
        if with_criteria:
            n["criteria"] = bool(n.get("criteria"))
        else:
            n.pop("criteria", None)
    return json.dumps(d, sort_keys=True)


def main() -> int:
    docs = [load(g) for g in iter_graphs()]
    # Only ONE number is reported, and it deliberately ignores `criteria`.
    # Criteria are prose, and prose is free: counting it would let a registry of
    # identical graphs look distinct because each was given a different sentence,
    # which is precisely the trick this metric exists to defeat. Criteria coverage
    # is reported separately, as coverage, not as distinctness.
    groups: dict[str, list[str]] = defaultdict(list)
    for d in docs:
        groups[_skeleton(d, with_criteria=False)].append(d["name"])
    clones = {k: v for k, v in groups.items() if len(v) > 1}
    verifiers = [n for d in docs for n in d["nodes"] if n.get("kind") == "verifier"]
    report: dict = {
        "total": len(docs),
        "distinct_topologies": len(groups),
        "graphs_sharing_a_topology": sum(len(v) for v in clones.values()),
        "verifiers_with_criteria": f"{sum(1 for n in verifiers if n.get('criteria'))}/{len(verifiers)}",
        "clusters": sorted((sorted(v) for v in clones.values()), key=len, reverse=True),
    }
    (ROOT / "reports" / "clones.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{report['total']} graphs -> {report['distinct_topologies']} distinct topologies; "
          f"{report['graphs_sharing_a_topology']} share one with another graph")
    print(f"verifiers carrying criteria: {report['verifiers_with_criteria']}")
    for c in report["clusters"]:
        print(f"  {len(c)}x {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
