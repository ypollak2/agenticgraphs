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
#: Node keys introduced in AGR v1.2.
_V12_NODE_KEYS = {"fan_out", "aggregate", "search"}


#: Names that appear in an assert but are never blackboard keys.
_ASSERT_LITERALS = {
    "trivial", "low", "simple", "medium", "moderate", "high", "complex", "critical",
    "true", "false", "null", "len", "all", "any", "sum", "min", "max", "abs", "round",
    "output",
}


def asserted_keys(expr: str) -> set[str]:
    """Blackboard keys a verification assert actually reads.

    `output.<attr>` accesses plus free bare names, minus comprehension-bound
    variables, level literals and builtins. AST rather than regex on purpose: a
    regex counted `f`, `v` and `for` as blackboard keys, which is exactly the
    kind of near-miss that makes a wrong number look like a finding.

    Returns an empty set for anything unparseable — `lint: verification assert is
    not a parseable expression` already reports that separately.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return set()
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.comprehension):
            for target in ast.walk(node.target):
                if isinstance(target, ast.Name):
                    bound.add(target.id)
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "output"):
            keys.add(node.attr)
        elif isinstance(node, ast.Name) and node.id not in _ASSERT_LITERALS and node.id not in bound:
            keys.add(node.id)
    return keys


def unconnected_keys(doc: dict) -> set[str]:
    """Keys the contract asserts on that nothing in the graph is declared to produce.

    THE v1.4 gap. A graph's node I/O contracts and its verification contract were
    two separate vocabularies with nothing checking they referred to the same
    things: 123 of 183 asserted keys across the registry were produced by no
    declared output. That is how four contracts stayed structurally valid, passed
    the whole suite, and were satisfiable by no model.
    """
    produced = {o for n in doc.get("nodes", []) for o in n.get("outputs") or []}
    produced |= set((doc.get("state") or {}).get("inputs") or [])
    # No early return for graphs that declare nothing. An earlier draft excused
    # them — "a node that declares nothing makes no promise to break" — and that
    # escape hatch swallowed exactly the case it most needed to catch:
    # `code-review-pipeline` asserted on `output.verdict` while declaring no
    # outputs at all, so it read as fully connected and was promoted to v1.4.
    # Declaring nothing is not a defence; it is the maximal form of the gap.
    needed: set[str] = set()
    for v in doc.get("verification") or []:
        if "assert" in v:
            needed |= asserted_keys(v["assert"])
    return needed - produced


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

    produced_all = {o for n in doc.get("nodes", []) for o in n.get("outputs") or []}
    supplied_all = set((doc.get("state") or {}).get("inputs") or [])
    # A phase is valid either as an unexpanded `kind: subgraph` node, or — once
    # expanded — as the id prefix its child's nodes now carry. Both forms are
    # validated: `agr validate` sees the authored doc, the harness the expanded one.
    phases = {n["id"] for n in doc.get("nodes", []) if n.get("kind") == "subgraph"}
    phases |= {n["id"].split(".")[0] for n in doc.get("nodes", []) if "." in n["id"]}
    for n in doc.get("nodes", []):
        v12 = _V12_NODE_KEYS & n.keys()
        if v12:
            used |= v12
        fo = n.get("fan_out")
        if fo and fo["over"] not in produced_all | supplied_all:
            errors.append(
                f"lint: node '{n['id']}' fans out over '{fo['over']}' which no node outputs "
                "and state.inputs does not supply — it would fan out over nothing"
            )
        ag = n.get("aggregate")
        if ag and ag["over"] not in produced_all | supplied_all:
            errors.append(
                f"lint: node '{n['id']}' aggregates '{ag['over']}' which nothing produces"
            )
        if n.get("kind") == "search":
            used.add("kind: search")
            if not _parses(n.get("search", {}).get("score", "")):
                errors.append(
                    f"lint: node '{n['id']}' search score is not a parseable expression"
                )
    for v in doc.get("verification") or []:
        if v.get("phase"):
            used.add("verification.phase")
            if v["phase"] not in phases:
                errors.append(
                    f"lint: verification phase '{v['phase']}' is not a kind: subgraph node"
                )
    if doc.get("memory"):
        used.add("memory")

    for e in doc.get("edges", []):
        if e.get("kind", "flow") != "flow":
            used.add("edge kind")
    if (doc.get("state") or {}).get("inputs"):
        used.add("state.inputs")
    if any("describe" in v for v in doc.get("verification") or []):
        used.add("verification.describe")

    v12_used = used & (_V12_NODE_KEYS | {"kind: search", "verification.phase", "memory"})
    if v12_used and doc.get("apiVersion") in ("agr/v1", "agr/v1.1"):
        errors.append(
            f"lint: uses v1.2 features {sorted(v12_used)} but declares apiVersion "
            f"'{doc.get('apiVersion')}' — bump to 'agr/v1.2'"
        )
    if used and doc.get("apiVersion") == "agr/v1":
        errors.append(
            f"lint: uses v1.1 features {sorted(used)} but declares apiVersion 'agr/v1' — "
            "bump to 'agr/v1.1'"
        )

    # Declared I/O contract: an input must be produced by a node that can actually
    # REACH this one, or supplied at graph entry. v1.1 checked set membership —
    # "does this key exist anywhere in the graph" — which passes even when the
    # only producer runs strictly downstream and the value can never arrive.
    # Reachability is only checkable now that v1.5 gave every dependent node an
    # output to be reachable *from*.
    supplied = set((doc.get("state") or {}).get("inputs") or [])
    reachable_out = _upstream_outputs(doc)
    for n in doc.get("nodes", []):
        unmet = set(n.get("inputs") or []) - reachable_out.get(n["id"], set()) - supplied
        if unmet:
            errors.append(
                f"lint: node '{n['id']}' declares inputs {sorted(unmet)} that no node "
                "reaching it outputs and state.inputs does not supply"
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

    return errors + _lint_v11(doc, root) + _lint_v14(doc) + _lint_v15(doc)


def _contract_gap_message(doc: dict) -> str | None:
    unmet = unconnected_keys(doc)
    if not unmet:
        return None
    return (
        f"verification asserts on {sorted(unmet)} which no node declares as an output "
        "and state.inputs does not supply"
    )


def _lint_v14(doc: dict) -> list[str]:
    """v1.4: the verification contract and the node I/O contracts must agree.

    An **error** at `apiVersion: agr/v1.4`; below that it is advisory and lives in
    `lint_advisories`, not here. Keeping advisories out of this list matters:
    every caller — `agr validate`, the `agr infuse` gate, the test suite — treats
    whatever `lint_graph` returns as fatal. An earlier draft returned warnings
    from here and instantly bricked mutation: `infuse` refused every graph with
    "infusion rejected by gate: warn: ...".
    """
    msg = _contract_gap_message(doc)
    if msg and doc.get("apiVersion") == "agr/v1.4":
        return [f"lint: {msg}"]
    return []


def _upstream_outputs(doc: dict) -> dict[str, set[str]]:
    """For each node, everything produced by a node that can reach it.

    Ancestors via any edge kind, with a visit guard for the retry loops the
    registry is full of. Fixed-point rather than a topological sort, because AGR
    graphs are deliberately cyclic.
    """
    by_id = {n["id"]: n for n in doc.get("nodes", [])}
    preds: dict[str, set[str]] = {nid: set() for nid in by_id}
    for e in doc.get("edges", []):
        if e["to"] in preds:
            preds[e["to"]].add(e["from"])
    up: dict[str, set[str]] = {nid: set() for nid in by_id}
    for _ in range(len(by_id) + 1):          # fixed point; graphs are small
        changed = False
        for nid in by_id:
            acc: set[str] = set()
            for p in preds[nid]:
                acc |= set(by_id[p].get("outputs") or []) | up.get(p, set())
            if acc != up[nid]:
                up[nid], changed = acc, True
        if not changed:
            break
    return up


def silent_nodes(doc: dict) -> list[str]:
    """Nodes that something depends on but which declare no outputs.

    THE v1.5 gap. 103 of 346 nodes (29%) were contractually silent, and every one
    of them fed a downstream node. v1.4's lint asked whether *verification* had
    producers; nothing asked whether a node's **successors** have anything to
    consume.

    It matters because of what a live model does with silence. Told only to
    "return the keys this step is responsible for", `position-a` in
    `ab-test-analysis` answered the question literally —
    `{"keys": ["recomputed_effect", "claimed_effect"]}` — naming keys instead of
    producing values, and the judge downstream received an empty blackboard.

    Terminal nodes are exempt: a node nothing depends on owes nothing.
    """
    has_successor = {e["from"] for e in doc.get("edges", [])}
    return [
        n["id"] for n in doc.get("nodes", [])
        if n["id"] in has_successor
        and n.get("kind") != "subgraph"  # a phase delegates; the child declares
        and not n.get("outputs")
    ]


def _silence_message(doc: dict) -> str | None:
    silent = silent_nodes(doc)
    if not silent:
        return None
    return (
        f"nodes {sorted(silent)} have outgoing edges but declare no outputs — "
        "their successors have nothing to consume"
    )


def joint_precondition_asserts(doc: dict) -> list[tuple[str, list[str]]]:
    """Asserts whose keys come from more than one producing node.

    Real but rare — 6 of 135. Advisory only: it is a documentation problem (the
    graph should say both facts must survive to the end), and inventing a
    `requires_all` field for six cases would be exactly the optional-and-unused
    surface this version exists to stop creating.
    """
    owner: dict[str, str] = {}
    for n in doc.get("nodes", []):
        for o in n.get("outputs") or []:
            owner.setdefault(o, n["id"])
    out: list[tuple[str, list[str]]] = []
    for v in doc.get("verification") or []:
        if "assert" not in v:
            continue
        producers = {owner[k] for k in asserted_keys(v["assert"]) if k in owner}
        if len(producers) > 1:
            out.append((v["assert"], sorted(producers)))
    return out


def _lint_v15(doc: dict) -> list[str]:
    msg = _silence_message(doc)
    if msg and doc.get("apiVersion") == "agr/v1.5":
        return [f"lint: {msg}"]
    return []


def lint_advisories(doc: dict) -> list[str]:
    """Non-fatal findings: true, worth surfacing, never a reason to refuse work.

    Kept strictly out of `lint_graph`, whose return value every caller treats as
    fatal — an earlier draft mixed them and `agr infuse` refused the whole
    registry with "rejected by gate: warn: ...".
    """
    out: list[str] = []
    gap = _contract_gap_message(doc)
    if gap and doc.get("apiVersion") != "agr/v1.4":
        out.append(f"warn: {gap} (declare them to reach apiVersion agr/v1.4)")
    silence = _silence_message(doc)
    if silence and doc.get("apiVersion") != "agr/v1.5":
        out.append(f"warn: {silence} (declare them to reach apiVersion agr/v1.5)")
    for expr, producers in joint_precondition_asserts(doc):
        out.append(
            f"warn: assert spans keys from {producers} — both must survive to the "
            f"end for the check to be meaningful: {expr}"
        )
    return out


def validate_graph_file(path: Path, root: Path = ROOT) -> list[str]:
    doc = load(path)
    errors = validate_schema(doc, "graph")
    if not errors:
        errors += lint_graph(doc, root)
    return errors
