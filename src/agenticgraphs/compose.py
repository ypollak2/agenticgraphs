"""M4: compose — sequentially chain two graphs into one bigger graph.

`compose(doc_a, doc_b)` bolts graph B onto the end of graph A: every terminal
node of A (no outgoing edges) gets an unconditional edge into every entry node
of B (no incoming *unconditional* edge — same definition `validate.lint_graph`
uses). Node ids are namespaced with an `a-`/`b-` prefix, but ONLY on
collision, so a clean pair like two unrelated graphs keeps its original,
readable ids.

Before touching anything we run a contract-compatibility check: the free
identifiers B's entry edges need (`when: "risk >= medium"` needs `risk`) must
be a subset of what A is known to produce. "Known to produce" is a heuristic
over what actually exists in the AGR v1 schema today (there is no formal
input/output contract on nodes) — it's the union of identifiers appearing in
A's `verification[].assert` strings (A's termination contract, in code form)
and identifiers appearing in any of A's edge `when` conditions (the
blackboard vocabulary A's own routing already depends on, and therefore
produces before routing). Both are ordinary Python expressions evaluated by
`harness.safe_eval`; `when` strings are always valid Python in this registry,
`assert` strings sometimes are not, hence the ast-based extractor tolerates
prose and returns an empty set instead of raising.

This heuristic is deliberately conservative in the false-negative direction
(it can be too strict and reject a genuinely fine composition) but is
schema-honest in the sense that it never invents a contract the schema
doesn't already carry.
"""
from __future__ import annotations

import ast

from .registry import SPEC_VERSION
from .validate import lint_graph, validate_schema

# Level-vocabulary literals (see harness.Level._ORDER) and builtins that show
# up as bare Names in assert/when expressions but are never blackboard keys.
_LITERALS = {
    "trivial", "low", "simple", "medium", "moderate", "high", "complex",
    "critical", "true", "false", "null", "len", "all", "any", "sum",
    "min", "max", "abs", "round",
}


class ComposeError(Exception):
    """Raised when two graphs cannot be safely composed."""


def _idents(expr: str) -> set[str]:
    """Free identifiers referenced by a Python expression string.

    Returns an empty set for anything that isn't parseable as an expression
    (many `verification[].assert` strings in this registry are still prose
    placeholders, not code) rather than raising.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.comprehension):
            for n in ast.walk(node.target):
                if isinstance(n, ast.Name):
                    bound.add(n.id)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    return names - _LITERALS - bound


def _entries(doc: dict) -> list[str]:
    """Nodes with no incoming *unconditional* edge — same rule as validate.lint_graph."""
    node_ids = [n["id"] for n in doc["nodes"]]
    incoming = {e["to"] for e in doc["edges"] if not e.get("when")}
    return [n for n in node_ids if n not in incoming]


def _terminals(doc: dict) -> list[str]:
    """Nodes with no outgoing edges at all — where a graph's flow ends."""
    has_outgoing = {e["from"] for e in doc["edges"]}
    return [n["id"] for n in doc["nodes"] if n["id"] not in has_outgoing]


def _entry_required(doc: dict) -> set[str]:
    """Blackboard keys B's entry-originating edges need before they can fire."""
    ents = set(_entries(doc))
    keys: set[str] = set()
    for e in doc["edges"]:
        if e["from"] in ents and e.get("when"):
            keys |= _idents(e["when"])
    return keys


def _edge_vocab(doc: dict) -> set[str]:
    """All blackboard keys referenced anywhere in this graph's routing."""
    keys: set[str] = set()
    for e in doc["edges"]:
        if e.get("when"):
            keys |= _idents(e["when"])
    return keys


def _contract_produced(doc: dict) -> set[str]:
    """Blackboard keys this graph's termination contract asserts on."""
    keys: set[str] = set()
    for v in doc.get("verification", []):
        if "assert" in v:
            keys |= _idents(v["assert"])
    return keys


def _declares_io(doc: dict) -> bool:
    """True if this graph carries an AGR v1.1 declared I/O contract."""
    return any(n.get("inputs") or n.get("outputs") for n in doc["nodes"])


def produced_keys(doc: dict) -> set[str]:
    """What a graph makes available on the blackboard.

    Prefers the v1.1 declared contract (`nodes[].outputs`). Falls back to the
    v1 heuristic — identifiers appearing in termination-contract asserts and in
    edge routing conditions — for the graphs that declare nothing.
    """
    if _declares_io(doc):
        return {o for n in doc["nodes"] for o in n.get("outputs") or []}
    return _contract_produced(doc) | _edge_vocab(doc)


def required_keys(doc: dict) -> set[str]:
    """What a graph needs before its entry nodes can proceed.

    Declared form: the `inputs` of entry nodes, minus anything the graph
    supplies itself via `state.inputs`. Heuristic fallback: identifiers in the
    `when` conditions on entry-originating edges.
    """
    if _declares_io(doc):
        ents = set(_entries(doc))
        need = {i for n in doc["nodes"] if n["id"] in ents for i in n.get("inputs") or []}
        return need - set((doc.get("state") or {}).get("inputs") or [])
    return _entry_required(doc)


def contract_basis(doc_a: dict, doc_b: dict) -> str:
    """Which check produced the verdict — reported so callers know its strength."""
    return "declared" if _declares_io(doc_a) and _declares_io(doc_b) else "heuristic"


def check_contract(doc_a: dict, doc_b: dict) -> set[str]:
    """Keys B needs on entry that A doesn't produce."""
    return required_keys(doc_b) - produced_keys(doc_a)


def compose_by_reference(doc_a: dict, doc_b: dict, name: str | None = None) -> dict:
    """v1.1 composition: a two-phase parent graph that *references* both graphs.

    Preferred over `compose()` when both graphs live in the registry. Nothing is
    spliced or renamed — the parent names each child with `kind: subgraph` and
    the runtime inlines them at load. Editing a child updates every composite
    that references it, which text-splicing can never do.
    """
    cat_a, cat_b = doc_a["category"], doc_b["category"]
    a_id, b_id = doc_a["name"], doc_b["name"]
    composed_name = (name or f"{a_id}-then-{b_id}")[:64]
    contracts = [d.get("termination", {}).get("contract") for d in (doc_a, doc_b)]
    contract = "; then ".join(c for c in contracts if c)
    # Child verification does not survive expansion (see subgraphs.expand), so a
    # composite that declares nothing verifies nothing — and the linter says so.
    # This function returned exactly such a graph and never checked it
    # (2026-09-04 audit, D4-04). Each child's checks come along phase-scoped, so
    # the harness evaluates them against the frame that phase actually produced.
    verification = [
        {**v, "phase": d["name"]}
        for d in (doc_a, doc_b)
        for v in (d.get("verification") or [])
    ]

    def _ver(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("/v")[1].split("."))

    api = max((doc_a.get("apiVersion", SPEC_VERSION), doc_b.get("apiVersion", SPEC_VERSION),
               SPEC_VERSION), key=_ver)
    composed = {
        "apiVersion": api,
        "name": composed_name,
        "description": f"Two-phase composite: {a_id} then {b_id}, each referenced as a subgraph.",
        "category": cat_a,
        "nodes": [
            {"id": a_id, "speciality": "supervisor", "kind": "subgraph", "ref": f"{cat_a}/{a_id}"},
            {"id": b_id, "speciality": "supervisor", "kind": "subgraph", "ref": f"{cat_b}/{b_id}",
             "join": "all"},
        ],
        "edges": [{"from": a_id, "to": b_id}],
        "termination": {
            "max_steps": sum(d.get("termination", {}).get("max_steps", 0) for d in (doc_a, doc_b)),
            **({"contract": contract} if contract else {}),
        },
        **({"verification": verification} if verification else {}),
    }
    goal = doc_a.get("goal") or doc_b.get("goal")
    if goal:
        composed["goal"] = goal
    state_inputs = sorted({k for d in (doc_a, doc_b) for k in (d.get("state") or {}).get("inputs", [])})
    if state_inputs:
        composed["state"] = {"inputs": state_inputs}
    errors = validate_schema(composed, "graph")
    if not errors:
        errors = lint_graph(composed)
    if errors:
        raise ComposeError("composed graph failed validation:\n" + "\n".join(f"  - {e}" for e in errors))
    return composed


def _namespace(nodes: list[dict], edges: list[dict], prefix: str, collisions: set[str]) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Prefix node ids that collide with the other graph's ids (only those).

    Returns (new_nodes, new_edges, remap) where remap maps old id -> new id
    for every id that was actually renamed.
    """
    remap = {n["id"]: (f"{prefix}-{n['id']}" if n["id"] in collisions else n["id"]) for n in nodes}
    new_nodes = []
    for n in nodes:
        nn = dict(n)
        nn["id"] = remap[n["id"]]
        new_nodes.append(nn)
    new_edges = []
    for e in edges:
        ne = dict(e)
        ne["from"] = remap[e["from"]]
        ne["to"] = remap[e["to"]]
        new_edges.append(ne)
    return new_nodes, new_edges, remap


def compose(doc_a: dict, doc_b: dict, name: str | None = None, allow_gaps: bool = False) -> tuple[dict, list[str]]:
    """Sequentially compose graph B after graph A.

    Every terminal node of A gets an unconditional edge to every entry node
    of B. Node ids are namespaced (`a-`/`b-`) only where the two graphs
    collide. Raises ComposeError if B needs blackboard keys A doesn't
    appear to produce, unless allow_gaps=True (in which case the gap is
    returned as a warning instead).

    Returns (composed_doc, warnings).
    """
    warnings: list[str] = []

    missing = check_contract(doc_a, doc_b)
    if missing:
        basis = contract_basis(doc_a, doc_b)
        how = (
            "declared v1.1 node inputs/outputs"
            if basis == "declared"
            else "heuristic: termination-contract asserts + edge routing vocabulary"
        )
        msg = (
            f"contract mismatch [{basis}]: '{doc_b['name']}' needs {sorted(missing)} "
            f"on entry, but '{doc_a['name']}' does not produce {sorted(missing)} "
            f"({how})"
        )
        if not allow_gaps:
            raise ComposeError(msg)
        warnings.append(f"warning: {msg} (bypassed via --allow-gaps)")

    a_nodes, a_edges = doc_a["nodes"], doc_a["edges"]
    b_nodes, b_edges = doc_b["nodes"], doc_b["edges"]

    a_ids = {n["id"] for n in a_nodes}
    b_ids = {n["id"] for n in b_nodes}
    collisions = a_ids & b_ids
    if collisions:
        warnings.append(f"namespaced colliding node ids: {sorted(collisions)}")

    a_nodes, a_edges, a_remap = _namespace(a_nodes, a_edges, "a", collisions)
    b_nodes, b_edges, b_remap = _namespace(b_nodes, b_edges, "b", collisions)

    a_terminals = [a_remap[t] for t in _terminals(doc_a)]
    b_entries = [b_remap[e] for e in _entries(doc_b)]
    if not a_terminals:
        raise ComposeError(f"'{doc_a['name']}' has no terminal node (every node has an outgoing edge) — cannot bridge")
    if not b_entries:
        raise ComposeError(f"'{doc_b['name']}' has no entry node (every node has an incoming unconditional edge) — cannot bridge")

    bridge_edges = [{"from": t, "to": e} for t in a_terminals for e in b_entries]

    composed_name = name or f"{doc_a['name']}-then-{doc_b['name']}"
    composed_name = composed_name[:64]

    contract_a = doc_a.get("termination", {}).get("contract")
    contract_b = doc_b.get("termination", {}).get("contract")
    if contract_a and contract_b:
        contract = f"{contract_a}; then {contract_b}"
    else:
        contract = contract_a or contract_b

    termination = {
        "max_steps": doc_a.get("termination", {}).get("max_steps", 0) + doc_b.get("termination", {}).get("max_steps", 0),
    }
    if contract:
        termination["contract"] = contract

    composed: dict = {
        "apiVersion": doc_a.get("apiVersion", "agr/v1"),
        "name": composed_name,
        "description": (
            f"Sequential composition: {doc_a['name']} feeds into {doc_b['name']}."
        )[:500],
        "category": doc_a["category"],
        "nodes": a_nodes + b_nodes,
        "edges": a_edges + b_edges + bridge_edges,
        "termination": termination,
    }
    verification = (doc_a.get("verification") or []) + (doc_b.get("verification") or [])
    if verification:
        composed["verification"] = verification
    state = doc_a.get("state") or doc_b.get("state")
    if state:
        composed["state"] = state

    errors = validate_schema(composed, "graph")
    if not errors:
        errors = lint_graph(composed)
    if errors:
        raise ComposeError("composed graph failed validation:\n" + "\n".join(f"  - {e}" for e in errors))

    return composed, warnings


def scaffold(doc: dict, children: list[dict], out_dir, root=None) -> list:
    """Write a composed graph as a registry-shaped bundle a human can finish.

    `agr compose -o file.yaml` produced a graph that validated and could never
    earn an eval verdict: no `cases.yaml`, no `usecase.yaml`, no `live/`
    (2026-09-04 audit, D4-05). This writes all four, deriving one golden case
    from each child's first case with node ids remapped to the composed graph,
    so `agr eval <name>` runs immediately and `agr validate` passes. The
    use-case row is a stub the author must complete; `audit_usecases.py` says
    what is missing.
    """
    from pathlib import Path

    import yaml as _yaml

    from .registry import ROOT, cases_path
    from .subgraphs import expand, has_subgraphs

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "graph.yaml").write_text(_yaml.safe_dump(doc, sort_keys=False, width=120))
    expanded = expand(doc, root or ROOT) if has_subgraphs(doc) else doc
    ids = {n["id"] for n in expanded["nodes"]}

    def remap(child: dict, nid: str) -> str | None:
        for cand in (f"{child['name']}.{nid}", nid, f"a-{nid}", f"b-{nid}"):
            if cand in ids:
                return cand
        return None

    node_outputs: dict = {}
    goals: list[str] = []
    inputs: dict = {}
    for child in children:
        cp = cases_path(child["name"], root or ROOT)
        if not cp.exists():
            continue
        first = _yaml.safe_load(cp.read_text())["cases"][0]
        for nid, out in first.get("node_outputs", {}).items():
            target = remap(child, nid)
            if target is not None:
                node_outputs[target] = out
        if first.get("goal"):
            goals.append(first["goal"])
        inputs.update(first.get("inputs") or {})
    case = {"id": "happy-path", "node_outputs": node_outputs}
    if goals:
        case["goal"] = "; then ".join(goals)
    if inputs:
        case["inputs"] = inputs
    (out_dir / "cases.yaml").write_text(_yaml.safe_dump({"cases": [case]}, sort_keys=False, width=120))
    (out_dir / "usecase.yaml").write_text(_yaml.safe_dump({
        "id": "uc-TODO",
        "pattern": "lifecycle",
        "summary": doc["description"].split("\n")[0][:120],
        "verification": (doc.get("termination") or {}).get("contract", "TODO: state the check"),
    }, sort_keys=False))
    (out_dir / "live").mkdir(exist_ok=True)
    (out_dir / "live" / ".gitkeep").write_text("")
    return sorted(p.relative_to(out_dir) for p in out_dir.rglob("*") if p.is_file())
