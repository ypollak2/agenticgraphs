"""v1.1: inline expansion of `kind: subgraph` nodes.

A subgraph node names another registry graph by `<category>/<name>`. Expansion
splices that graph's nodes into the parent, prefixing every child id with the
parent node's id (`implement` + `repro` -> `implement.repro`), and rewiring the
parent's edges to the child's entry/terminal nodes.

Inline expansion — rather than recursive execution — is a deliberate trade
(see docs/plans/v2-agr-1.1.md, D2). It keeps `run_graph`, `agr adapt`,
`agr mermaid` and `structural_profile` working unchanged on a flat node list,
and keeps traces readable. The cost is that a subgraph cannot enforce its own
`max_steps`; the parent's cap absorbs the child's (they are summed here).
"""
from __future__ import annotations

from pathlib import Path

from .registry import ROOT, load

MAX_DEPTH = 3


class SubgraphError(Exception):
    """Raised when a subgraph reference cannot be resolved or would recurse."""


def has_subgraphs(doc: dict) -> bool:
    return any(n.get("kind") == "subgraph" for n in doc.get("nodes", []))


def entry_nodes(doc: dict) -> list[str]:
    """Nodes the graph can start at: no incoming *forward* edge of any kind.

    THE canonical definition — `validate.lint_graph`, `harness.run_graph` and
    `compose` all call it, and they must agree. Two failures shaped this rule:

    * "no incoming edge at all" made any graph whose retry edge pointed back at
      its first node entry-less, so it executed zero steps while linting clean.
    * "no incoming *unconditional flow* edge" let a node reachable only by an
      error or compensate edge look like a start node — a rollback handler fired
      as step two of a release lifecycle, before the thing it compensates ran.

    So: direction decides. A *backward* edge (retry, compensation) never
    disqualifies a node, because it cannot be how the graph begins. Any forward
    edge does, whatever its kind or condition — a node something else routes to
    is not a start node. Whether a non-entry node is *ready* once it is queued
    is a separate question, answered by its join rule at run time.
    """
    order = {n["id"]: i for i, n in enumerate(doc["nodes"])}
    reached_forward = {
        e["to"]
        for e in doc["edges"]
        if order.get(e["to"], 0) > order.get(e["from"], -1)
    }
    return [n["id"] for n in doc["nodes"] if n["id"] not in reached_forward]


_entries = entry_nodes  # internal alias


def _terminals(doc: dict) -> list[str]:
    """Nodes with no outgoing *forward* flow edge — where a graph's flow ends.

    Back-edges are excluded, otherwise any graph with a retry loop would report
    no terminal at all: in `plan -> execute -> verify -> execute`, `verify`'s
    only outgoing edge is the retry, and `verify` is exactly the node a parent
    should continue from.
    """
    order = {n["id"]: i for i, n in enumerate(doc["nodes"])}
    has_fwd_out = {
        e["from"]
        for e in doc["edges"]
        if e.get("kind", "flow") == "flow" and order.get(e["to"], 0) > order.get(e["from"], -1)
    }
    return [n["id"] for n in doc["nodes"] if n["id"] not in has_fwd_out]


def _resolve(ref: str, root: Path) -> dict:
    path = root / "graphs" / ref / "graph.yaml"
    if not path.exists():
        raise SubgraphError(f"subgraph ref '{ref}' does not resolve to {path}")
    return load(path)


def expand(doc: dict, root: Path = ROOT, _depth: int = 0, _path: tuple[str, ...] = ()) -> dict:
    """Return a copy of `doc` with every `kind: subgraph` node inlined.

    Idempotent on graphs that contain no subgraph nodes: returns `doc` itself.
    """
    if not has_subgraphs(doc):
        return doc
    if _depth >= MAX_DEPTH:
        raise SubgraphError(
            f"subgraph nesting exceeds MAX_DEPTH={MAX_DEPTH} at {' -> '.join(_path)}"
        )

    nodes: list[dict] = []
    edges: list[dict] = list(doc["edges"])
    verification: list[dict] = list(doc.get("verification") or [])
    extra_steps = 0

    for node in doc["nodes"]:
        if node.get("kind") != "subgraph":
            nodes.append(dict(node))
            continue

        ref = node["ref"]
        if ref in _path:
            raise SubgraphError(
                f"subgraph cycle: {' -> '.join((*_path, ref))}"
            )
        child = expand(_resolve(ref, root), root, _depth + 1, (*_path, ref))

        prefix = node["id"]
        remap = {c["id"]: f"{prefix}.{c['id']}" for c in child["nodes"]}
        child_entries = [remap[e] for e in _entries(child)]
        child_terminals = [remap[t] for t in _terminals(child)]
        if not child_entries or not child_terminals:
            raise SubgraphError(
                f"subgraph '{ref}' has no entry or no terminal node — cannot splice"
            )

        for c in child["nodes"]:
            cn = dict(c)
            cn["id"] = remap[c["id"]]
            # The phase node's declared contract transfers to the child's
            # boundary: what the phase reads is read on entry, what the phase
            # is contracted to produce is produced by the time flow leaves it.
            # Without this the I/O contract would evaporate on expansion.
            if cn["id"] in child_entries:
                if node.get("join"):
                    cn["join"] = node["join"]
                if node.get("inputs"):
                    cn["inputs"] = sorted({*(cn.get("inputs") or []), *node["inputs"]})
            if cn["id"] in child_terminals and node.get("outputs"):
                cn["outputs"] = sorted({*(cn.get("outputs") or []), *node["outputs"]})
            nodes.append(cn)
        for ce in child["edges"]:
            e = dict(ce)
            e["from"], e["to"] = remap[ce["from"]], remap[ce["to"]]
            edges.append(e)

        # Rewire the parent's edges touching this node onto the child's boundary.
        rewired: list[dict] = []
        for e in edges:
            if e["from"] != prefix and e["to"] != prefix:
                rewired.append(e)
                continue
            froms = child_terminals if e["from"] == prefix else [e["from"]]
            tos = child_entries if e["to"] == prefix else [e["to"]]
            for f in froms:
                for t in tos:
                    ne = dict(e)
                    ne["from"], ne["to"] = f, t
                    rewired.append(ne)
        edges = rewired

        # v1.2: child verification IS merged now — tagged with the phase id so
        # the harness evaluates it against that phase's terminal frame rather
        # than the final blackboard. The v1.1 note below explains why it had to
        # wait for frames; the lint requiring composites to declare their own
        # verification stays as belt and braces.
        verification += [{**v, "phase": prefix} for v in (child.get("verification") or [])]

        # (v1.1 rationale, retained because it explains the design:)
        #
        # Every graph in the registry writes its result to a single `output`
        # key, so a child's asserts (`output.coverage_delta > 0`) only hold at
        # the instant that child's terminal node ran. Merged into a parent whose
        # own terminal later overwrites `output`, they evaluate against the wrong
        # snapshot and fail for a reason that has nothing to do with the phase.
        #
        # Evaluating them correctly needs per-phase blackboard snapshots, which
        # is the same machinery v1.2 introduces for `memory`. Until then the rule
        # is: embedding a graph as a phase makes the parent responsible for
        # declaring what that phase must have achieved. `lint: subgraph without
        # verification` enforces that the parent does not simply stay silent.
        extra_steps += child.get("termination", {}).get("max_steps", 0)

    out = dict(doc)
    # Expansion emits phase-tagged verification, which is a v1.2 feature —
    # the expanded doc must declare the version whose surface it actually uses.
    out["apiVersion"] = "agr/v1.2"
    out["nodes"] = nodes
    out["edges"] = edges
    if verification:
        out["verification"] = verification
    term = dict(doc["termination"])
    term["max_steps"] = term["max_steps"] + extra_steps
    out["termination"] = term
    return out
