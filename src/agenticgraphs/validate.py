"""Schema + structural validation for AGR graphs.

Structural lint encodes known multi-agent failure modes (MAST taxonomy):
unreachable nodes, dangling edges, missing verification, unbounded loops,
and unresolvable specialities/abilities.

v1.1 adds lints for the new surface: subgraph refs that resolve, declared I/O
contracts that are actually satisfiable, approval contracts and verification
asserts that parse, and a guard against using v1.1 features under an
`agr/v1` apiVersion.
"""
from __future__ import annotations

import ast
from pathlib import Path

import jsonschema

from .registry import ROOT, iter_yaml, load, load_schema
from .subgraphs import entry_nodes

#: Node/edge/graph keys introduced in AGR v1.1.
_V11_NODE_KEYS = {"ref", "join", "inputs", "outputs", "on_error", "retries", "approval"}


def _parses(expr: str) -> bool:
    try:
        ast.parse(expr, mode="eval")
    except SyntaxError:
        return False
    return True


def _lint_v11(doc: dict, root: Path) -> list[str]:
    """Lints for the AGR v1.1 surface. Returns [] for a pure-v1 graph."""
    errors: list[str] = []
    node_ids = {n["id"] for n in doc.get("nodes", [])}
    used: set[str] = set()

    for n in doc.get("nodes", []):
        used |= _V11_NODE_KEYS & n.keys()
        if n.get("kind") == "subgraph":
            used.add("kind: subgraph")
            ref = n.get("ref", "")
            if not (root / "graphs" / ref / "graph.yaml").exists():
                errors.append(f"lint: node '{n['id']}' subgraph ref '{ref}' does not resolve")
            # Child verification does not survive expansion (see subgraphs.expand),
            # so a composite that declares nothing verifies nothing.
            if not doc.get("verification"):
                errors.append(
                    f"lint: node '{n['id']}' embeds subgraph '{ref}' but the graph declares no "
                    "verification — a composite must state what its phases achieved"
                )
        if n.get("kind") == "human":
            contract = (n.get("approval") or {}).get("contract", "")
            if contract and not _parses(contract):
                errors.append(
                    f"lint: node '{n['id']}' approval contract is not a parseable expression: {contract!r}"
                )
        if n.get("on_error") and n["on_error"] not in node_ids:
            errors.append(f"lint: node '{n['id']}' on_error targets unknown node '{n['on_error']}'")

    for e in doc.get("edges", []):
        if e.get("kind", "flow") != "flow":
            used.add("edge kind")
    if (doc.get("state") or {}).get("inputs"):
        used.add("state.inputs")
    if any("describe" in v for v in doc.get("verification") or []):
        used.add("verification.describe")

    if used and doc.get("apiVersion") == "agr/v1":
        errors.append(
            f"lint: uses v1.1 features {sorted(used)} but declares apiVersion 'agr/v1' — "
            "bump to 'agr/v1.1'"
        )

    # Declared I/O contract: every input must be produced upstream, or supplied
    # at graph entry. Only checked for nodes that opt in by declaring `inputs`.
    supplied = set((doc.get("state") or {}).get("inputs") or [])
    produced = {o for n in doc.get("nodes", []) for o in n.get("outputs") or []}
    for n in doc.get("nodes", []):
        unmet = set(n.get("inputs") or []) - produced - supplied
        if unmet:
            errors.append(
                f"lint: node '{n['id']}' declares inputs {sorted(unmet)} that no node "
                "outputs and state.inputs does not supply"
            )

    # A saga must be able to undo itself: any node holding an execute-risk
    # ability needs an outgoing compensate edge.
    if doc.get("name", "").endswith("-saga"):
        risks = {load(p)["name"]: load(p).get("risk") for p in iter_yaml("abilities", root)}
        compensating = {e["from"] for e in doc.get("edges", []) if e.get("kind") == "compensate"}
        # The compensators themselves are the undo path — they do not need one.
        compensators = {e["to"] for e in doc.get("edges", []) if e.get("kind") == "compensate"}
        chained = set(compensators)
        for _ in range(len(doc.get("nodes", []))):  # follow compensator -> compensator chains
            chained |= {e["to"] for e in doc.get("edges", []) if e["from"] in chained}
        for n in doc.get("nodes", []):
            if n["id"] in chained:
                continue
            if any(risks.get(a) == "execute" for a in n.get("abilities") or []):
                if n["id"] not in compensating:
                    errors.append(
                        f"lint: saga node '{n['id']}' has an execute-risk ability but no "
                        "compensate edge — the step cannot be undone"
                    )
    return errors


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
    entries = entry_nodes(doc)
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

    # unbounded loop guard: any back-edge must carry a 'when' condition.
    # Compensate edges are reverse paths by construction and are exempt.
    order = {nid: i for i, nid in enumerate(node_ids)}
    for e in doc.get("edges", []):
        if e.get("kind") == "compensate":
            continue
        if order.get(e["to"], 0) <= order.get(e["from"], 0) and not e.get("when"):
            errors.append(f"lint: unconditional back-edge {e['from']}->{e['to']}")

    # verification asserts must be evaluable expressions, not prose
    for v in doc.get("verification", []):
        if "assert" in v and not _parses(v["assert"]):
            errors.append(f"lint: verification assert is not a parseable expression: {v['assert']!r}")

    # speciality / ability resolution
    specs = {load(p)["name"]: load(p) for p in iter_yaml("specialities", root)}
    abilities = {load(p)["name"] for p in iter_yaml("abilities", root)}
    for n in doc.get("nodes", []):
        s = specs.get(n["speciality"])
        if s is None:
            errors.append(f"lint: node '{n['id']}' unknown speciality '{n['speciality']}'")
            continue
        if n.get("kind") == "subgraph":
            continue  # a subgraph node delegates; its abilities live in the child graph
        declared = set(n.get("abilities", []))
        missing_req = set(s["requires_abilities"]) - declared
        if missing_req:
            errors.append(f"lint: node '{n['id']}' missing required abilities {sorted(missing_req)}")
        unknown = declared - abilities
        if unknown:
            errors.append(f"lint: node '{n['id']}' unknown abilities {sorted(unknown)}")

    return errors + _lint_v11(doc, root)


def validate_graph_file(path: Path, root: Path = ROOT) -> list[str]:
    doc = load(path)
    errors = validate_schema(doc, "graph")
    if not errors:
        errors += lint_graph(doc, root)
    return errors
