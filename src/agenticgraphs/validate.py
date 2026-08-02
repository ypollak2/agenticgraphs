"""Schema + structural validation for AGR graphs.

Structural lint encodes known multi-agent failure modes (MAST taxonomy):
unreachable nodes, dangling edges, missing verification, unbounded loops,
and unresolvable specialities/abilities.
"""
from __future__ import annotations

from pathlib import Path

import jsonschema

from .registry import ROOT, iter_yaml, load, load_schema


def validate_schema(doc: dict, kind: str) -> list[str]:
    v = jsonschema.Draft202012Validator(load_schema(kind))
    return [f"schema: {e.message}" for e in v.iter_errors(doc)]


def lint_graph(doc: dict, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    node_ids = [n["id"] for n in doc.get("nodes", [])]
    if len(node_ids) != len(set(node_ids)):
        errors.append("lint: duplicate node ids")

    # dangling edges
    for e in doc.get("edges", []):
        for end in ("from", "to"):
            if e[end] not in node_ids:
                errors.append(f"lint: edge references unknown node '{e[end]}'")

    # reachability from entry nodes: a node is an entry if it has no incoming
    # *unconditional* edge (conditional back-edges do not define forward flow)
    incoming = {e["to"] for e in doc.get("edges", []) if not e.get("when")}
    entries = [n for n in node_ids if n not in incoming]
    if not entries:
        errors.append("lint: no entry node (cycle with no way in)")
    seen, frontier = set(entries), list(entries)
    while frontier:
        cur = frontier.pop()
        for e in doc.get("edges", []):
            if e["from"] == cur and e["to"] not in seen:
                seen.add(e["to"])
                frontier.append(e["to"])
    unreachable = set(node_ids) - seen
    if unreachable:
        errors.append(f"lint: unreachable nodes {sorted(unreachable)}")

    # verification required for graphs with a verifier node
    if any(n.get("kind") == "verifier" for n in doc.get("nodes", [])) and not doc.get("verification"):
        errors.append("lint: graph has verifier node but no verification block")

    # unbounded loop guard: any back-edge must carry a 'when' condition
    order = {nid: i for i, nid in enumerate(node_ids)}
    for e in doc.get("edges", []):
        if order.get(e["to"], 0) <= order.get(e["from"], 0) and not e.get("when"):
            errors.append(f"lint: unconditional back-edge {e['from']}->{e['to']}")

    # speciality / ability resolution
    specs = {load(p)["name"]: load(p) for p in iter_yaml("specialities", root)}
    abilities = {load(p)["name"] for p in iter_yaml("abilities", root)}
    for n in doc.get("nodes", []):
        s = specs.get(n["speciality"])
        if s is None:
            errors.append(f"lint: node '{n['id']}' unknown speciality '{n['speciality']}'")
            continue
        declared = set(n.get("abilities", []))
        missing_req = set(s["requires_abilities"]) - declared
        if missing_req:
            errors.append(f"lint: node '{n['id']}' missing required abilities {sorted(missing_req)}")
        unknown = declared - abilities
        if unknown:
            errors.append(f"lint: node '{n['id']}' unknown abilities {sorted(unknown)}")
    return errors


def validate_graph_file(path: Path, root: Path = ROOT) -> list[str]:
    doc = load(path)
    errors = validate_schema(doc, "graph")
    if not errors:
        errors += lint_graph(doc, root)
    return errors
