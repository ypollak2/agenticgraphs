"""Declare each asserted key on the node that actually establishes it.

v1.3 tried to fix four unsatisfiable contracts by declaring their asserted keys on
the *terminal* node. All 12 re-recorded runs failed, because the terminal only
*assembles* `output` — the facts inside it come from upstream. `ab-test-analysis`
needs `claimed_effect` from intake and `recomputed_effect` from the analysis step;
asking one node for both asks it to report facts it never had.

Which node establishes which key is not guessable from the YAML, but it is
recorded: every graph has a golden case naming, per node, exactly what that node
emits. This reads those fixtures and puts each declaration where the evidence says
it belongs.

**No assert is ever modified.** The cheap way to make 123 unmet keys disappear is
to delete the asserts that reference them; this script only adds `outputs`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import ROOT, iter_graphs, load  # noqa: E402
from agenticgraphs.subgraphs import expand, has_subgraphs  # noqa: E402
from agenticgraphs.validate import (  # noqa: E402
    asserted_keys,
    silent_nodes,
    unconnected_keys,
)


def _emitters(cases: list[dict]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(node -> keys it emits at top level, node -> keys it emits inside `output`)."""
    top: dict[str, set[str]] = {}
    nested: dict[str, set[str]] = {}
    for case in cases:
        for nid, out in case["node_outputs"].items():
            for visit in (out if isinstance(out, list) else [out]):
                if not isinstance(visit, dict):
                    continue
                top.setdefault(nid, set()).update(k for k in visit if k != "output")
                inner = visit.get("output")
                if isinstance(inner, dict):
                    nested.setdefault(nid, set()).update(inner)
    return top, nested


def derive(gpath: Path) -> tuple[str, list[str], list[str]]:
    doc = load(gpath)
    name = doc["name"]
    cases_file = ROOT / "evals" / name / "cases.yaml"
    if not cases_file.exists():
        return name, [], []
    cases = yaml.safe_load(cases_file.read_text())["cases"]

    # Asserted keys are read off the *expanded* graph, because a composite
    # inherits its children's phase-tagged contracts.
    expanded = expand(doc, ROOT) if has_subgraphs(doc) else doc
    needed: set[str] = set()
    for v in expanded.get("verification") or []:
        if "assert" in v:
            needed |= asserted_keys(v["assert"])

    top, nested = _emitters(cases)
    by_id = {n["id"]: n for n in doc["nodes"]}
    added: list[str] = []
    unresolved: list[str] = []

    # v1.5: every node that something depends on must declare what it produces,
    # not only the keys verification happens to assert on. 103 of 346 nodes were
    # contractually silent, and a live model told to "return the keys this step is
    # responsible for" answers that question literally — naming keys instead of
    # producing values, and starving everything downstream.
    has_successor = {e["from"] for e in doc["edges"]}
    for nid, node in by_id.items():
        if nid not in has_successor or node.get("kind") == "subgraph":
            continue
        emitted = set(top.get(nid, ())) | set(nested.get(nid, ()))
        # A composite phase's fixtures live under `<phase>.<child>`; roll them up.
        for fixture_id, keys in {**top, **nested}.items():
            if fixture_id.split(".")[0] == nid and fixture_id != nid:
                emitted |= set(keys)
        emitted -= {"attempts"}  # runtime-owned, never a node's to promise
        if emitted and not node.get("outputs"):
            node["outputs"] = sorted(emitted)
            added += [f"{nid}.{k}" for k in sorted(emitted)]

    for key in sorted(needed):
        # Prefer the node that emits the fact directly; fall back to the node that
        # carries it inside `output`. A composite's child node ids are prefixed,
        # so map them back to the phase that owns them.
        owner = next((nid for nid, keys in top.items() if key in keys), None)
        if owner is None:
            owner = next((nid for nid, keys in nested.items() if key in keys), None)
        if owner is None:
            unresolved.append(key)
            continue
        target = owner if owner in by_id else owner.split(".")[0]
        node = by_id.get(target)
        if node is None:
            unresolved.append(key)
            continue
        if key not in (node.get("outputs") or []):
            node["outputs"] = sorted({*(node.get("outputs") or []), key})
            added.append(f"{target}.{key}")

    if added:
        doc["apiVersion"] = "agr/v1.5"
        gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    elif (not unconnected_keys(doc) and not silent_nodes(doc)
          and doc.get("apiVersion") != "agr/v1.5"):
        doc["apiVersion"] = "agr/v1.5"  # already fully declared; promote it
        gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    return name, added, unresolved


def main() -> int:
    total_added = 0
    stuck: list[tuple[str, list[str]]] = []
    for gpath in iter_graphs():
        name, added, unresolved = derive(gpath)
        total_added += len(added)
        if unresolved:
            stuck.append((name, unresolved))
    print(f"declared {total_added} keys on the nodes their fixtures show producing them")
    if stuck:
        print(f"\n{len(stuck)} graphs have keys no fixture emits — these need a human:")
        for name, keys in stuck:
            print(f"  {name:40s} {keys}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
