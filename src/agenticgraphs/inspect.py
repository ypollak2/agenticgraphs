"""Graph inspection: lookup, mermaid export, structural profile.

Structural profiles are deterministic facts about the artifact (topology, bounds,
risk surface). They are NOT performance measurements — that's M1's eval harness.
"""
from __future__ import annotations

import json
from pathlib import Path

from .registry import ROOT, graph_dir, iter_yaml, load

RISK_ORDER = {"read": 0, "write": 1, "execute": 2}


def find_graph(name: str, root: Path = ROOT) -> Path | None:
    """The graph.yaml for `name`. One definition of the lookup, in the core."""
    d = graph_dir(name, root)
    return (d / "graph.yaml") if d is not None else None


def to_mermaid(doc: dict) -> str:
    alias = {n["id"]: f"N{i}" for i, n in enumerate(doc["nodes"])}
    lines = ["flowchart LR"]
    for n in doc["nodes"]:
        label = f'{n["id"]}<br/><i>{n["speciality"]}</i>'
        a = alias[n["id"]]
        kind = n.get("kind", "agent")
        if kind == "verifier":
            lines.append(f'    {a}{{{{"{label}"}}}}')
        elif kind == "router":
            lines.append(f'    {a}[/"{label}"/]')
        else:
            lines.append(f'    {a}["{label}"]')
    for e in doc["edges"]:
        arrow = f'-->|{e["when"]}|' if e.get("when") else "-->"
        lines.append(f'    {alias[e["from"]]} {arrow} {alias[e["to"]]}')
    return "\n".join(lines)


def ability_risks(root: Path = ROOT) -> dict[str, str]:
    """Declared risk per ability name.

    Its own function so a caller profiling the whole registry can build it once.
    The inline version read every ability file *twice* per graph — 5312 reads to
    profile 83 graphs, which dwarfed the join it was part of.
    """
    out = {}
    for p in iter_yaml("abilities", root):
        doc = load(p)
        out[doc["name"]] = doc.get("risk", "read")
    return out


def structural_profile(doc: dict, root: Path = ROOT,
                       ability_risk: dict[str, str] | None = None) -> dict:
    nodes, edges = doc["nodes"], doc["edges"]
    if ability_risk is None:
        ability_risk = ability_risks(root)
    risks = [ability_risk.get(a, "read") for n in nodes for a in n.get("abilities", [])]
    order = {nid: i for i, nid in enumerate(n["id"] for n in nodes)}
    back_edges = [e for e in edges if order.get(e["to"], 0) <= order.get(e["from"], 0)]
    fan_out: dict[str, int] = {}
    for e in edges:
        fan_out[e["from"]] = fan_out.get(e["from"], 0) + 1
    return {
        "name": doc["name"],
        "category": doc["category"],
        "structural": {
            "nodes": len(nodes),
            "edges": len(edges),
            "verifier_nodes": sum(1 for n in nodes if n.get("kind") == "verifier"),
            "router_nodes": sum(1 for n in nodes if n.get("kind") == "router"),
            "parallel_groups": len({n["parallel_group"] for n in nodes if n.get("parallel_group")}),
            "max_fan_out": max(fan_out.values(), default=0),
            "loops": len(back_edges),
            "loops_bounded": all(e.get("when") for e in back_edges),
            "max_steps": doc["termination"]["max_steps"],
            "verification_asserts": len(doc.get("verification", [])),
            "risk_surface": max(risks, key=lambda r: RISK_ORDER[r], default="read"),
        },
        "measured": None,  # M1: eval harness fills quality/cost/robustness here
    }


def render_profile(doc: dict, root: Path = ROOT) -> str:
    return json.dumps(structural_profile(doc, root), indent=2)
