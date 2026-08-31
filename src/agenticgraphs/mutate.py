"""M2: mutation is first-class — infuse abilities, optimize structure.

Every mutation is gate-checked (schema + MAST lint, and golden cases when they
exist) and logged to a lineage.yaml sidecar next to the graph. The optimizer is
a v0 deterministic hill-climb over safe structural operators; AFlow-style MCTS
over the full space is future work and is labeled as such.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .autonomy import commit_autonomous_mutation, require_autonomous, require_execute_allowed
from .evalcmd import case_inputs
from .harness import MockRunner, run_graph
from .inspect import find_graph
from .registry import ROOT, cases_path, iter_yaml, load
from .validate import validate_graph_file


def _lineage_append(gdir: Path, entry: dict) -> None:
    lf = gdir / "lineage.yaml"
    log = yaml.safe_load(lf.read_text()) if lf.exists() else {"mutations": []}
    log["mutations"].append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry})
    lf.write_text(yaml.safe_dump(log, sort_keys=False))


def _write_checked(gpath: Path, doc: dict, original: str) -> list[str]:
    gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=120))
    errs = validate_graph_file(gpath)
    if errs:
        gpath.write_text(original)  # rollback — mutations never leave a broken registry
    return errs


def _cases_still_pass(name: str, doc: dict, root: Path = ROOT) -> bool:
    """Replay the golden cases against a mutated doc, exactly as `eval_graph` would.

    Seeding `case_inputs` is not optional. Every graph declares `goal.required`
    as of v1.8, so a replay that omits the case's goal makes the graph refuse
    before it schedules a node — every case "fails", every operator is reverted,
    and `optimize` silently proposes nothing on a registry where it previously
    worked. A safety check that rejects everything is indistinguishable from one
    that is broken, which is why this shares `case_inputs` with the evaluator
    rather than rebuilding the seed.
    """
    cf = cases_path(name, root)
    if not cf.exists():
        return True
    for case in yaml.safe_load(cf.read_text())["cases"]:
        rep = run_graph(doc, MockRunner(case["node_outputs"]), inputs=case_inputs(case))
        if not rep.passed:
            return False
    return True


def infuse(name: str, node_id: str, ability: str, root: Path = ROOT) -> dict:
    gpath = find_graph(name, root)
    if gpath is None:
        raise SystemExit(f"no graph named '{name}'")
    known = {load(p)["name"] for p in iter_yaml("abilities", root)}
    if ability not in known:
        raise SystemExit(f"unknown ability '{ability}' — add abilities/{ability}.yaml first")
    doc = load(gpath)
    node = next((n for n in doc["nodes"] if n["id"] == node_id), None)
    if node is None:
        raise SystemExit(f"graph '{name}' has no node '{node_id}'")
    if ability in node.get("abilities", []):
        return {"changed": False, "reason": "ability already present"}
    original = gpath.read_text()
    node.setdefault("abilities", []).append(ability)
    errs = _write_checked(gpath, doc, original)
    if errs:
        raise SystemExit("infusion rejected by gate:\n" + "\n".join(errs))
    _lineage_append(gpath.parent, {"op": "infuse", "node": node_id, "ability": ability})
    return {"changed": True, "node": node_id, "ability": ability}


def infuse_autonomous(name: str, node_id: str, ability: str, root: Path = ROOT) -> dict:
    """Like `infuse`, but for unattended runs: requires AGR_AUTONOMOUS=1, caps
    execute-risk abilities behind AGR_AUTONOMOUS_ALLOW_EXECUTE=1, and — on a
    real change — commits the mutated graph + lineage onto `auto/mutations`
    (never `main`, never pushed). Raises AutonomyError if the gate is closed.
    """
    require_autonomous()
    ability_doc = next((load(p) for p in iter_yaml("abilities", root) if load(p)["name"] == ability), None)
    if ability_doc is not None:
        require_execute_allowed(ability_doc.get("risk", "read"))
    result = infuse(name, node_id, ability, root)
    if result.get("changed"):
        gpath = find_graph(name, root)
        commit = commit_autonomous_mutation(
            root,
            [gpath, gpath.parent / "lineage.yaml"],
            f"auto: {name} {ability} {node_id} [autonomous]",
        )
        result["commit"] = commit
        result["branch"] = "auto/mutations"
    return result


# ---- optimizer operators: each takes doc (+context) and returns list of change notes


def op_dedupe_edges(doc: dict, ctx: dict) -> list[str]:
    seen, kept, notes = set(), [], []
    for e in doc["edges"]:
        key = (e["from"], e["to"], e.get("when"))
        if key in seen:
            notes.append(f"dropped duplicate edge {e['from']}->{e['to']}")
        else:
            seen.add(key)
            kept.append(e)
    doc["edges"] = kept
    return notes


def op_parallelize_siblings(doc: dict, ctx: dict) -> list[str]:
    """Siblings fed by the same single parent with no edges between them can run in parallel."""
    parents: dict[str, set] = {}
    for e in doc["edges"]:
        parents.setdefault(e["to"], set()).add(e["from"])
    inter = {(e["from"], e["to"]) for e in doc["edges"]}
    by_parent: dict[str, list] = {}
    for n in doc["nodes"]:
        p = parents.get(n["id"])
        if p and len(p) == 1 and not n.get("parallel_group") and n.get("kind", "agent") == "agent":
            by_parent.setdefault(next(iter(p)), []).append(n)
    notes = []
    for parent, sibs in by_parent.items():
        if len(sibs) < 2:
            continue
        if any((a["id"], b["id"]) in inter or (b["id"], a["id"]) in inter for a in sibs for b in sibs if a is not b):
            continue
        for n in sibs:
            n["parallel_group"] = f"auto-{parent}"
        notes.append(f"parallelized {len(sibs)} siblings of '{parent}' into group 'auto-{parent}'")
    return notes


def op_tighten_max_steps(doc: dict, ctx: dict) -> list[str]:
    """Measurement-driven: shrink the step budget toward observed worst-case (profile.json)."""
    prof = ctx.get("profile")
    if not prof or not prof.get("measured") or prof["measured"]["pass_rate"] != 1.0:
        return []
    worst = max(r["steps"] for r in prof["measured"]["results"])
    proposed = max(worst * 2, worst + 2)
    if proposed < doc["termination"]["max_steps"]:
        old = doc["termination"]["max_steps"]
        doc["termination"]["max_steps"] = proposed
        return [f"max_steps {old} -> {proposed} (observed worst-case {worst} across passing cases)"]
    return []


OPERATORS = [op_dedupe_edges, op_parallelize_siblings, op_tighten_max_steps]


def optimize(name: str, apply: bool = False, root: Path = ROOT) -> dict:
    gpath = find_graph(name, root)
    if gpath is None:
        raise SystemExit(f"no graph named '{name}'")
    doc = load(gpath)
    original = gpath.read_text()
    pf = gpath.parent / "profile.json"
    ctx = {"profile": json.loads(pf.read_text()) if pf.exists() else None}
    notes: list[str] = []
    for op in OPERATORS:
        before = yaml.safe_dump(doc)
        applied = op(doc, ctx)
        if applied and not _cases_still_pass(name, doc, root):
            doc = yaml.safe_load(before)  # revert this operator: it broke golden cases
            continue
        notes.extend(applied)
    if not notes:
        return {"changed": False, "notes": []}
    if apply:
        errs = _write_checked(gpath, doc, original)
        if errs:
            raise SystemExit("optimization rejected by gate:\n" + "\n".join(errs))
        _lineage_append(gpath.parent, {"op": "optimize", "changes": notes})
    return {"changed": apply, "notes": notes}
