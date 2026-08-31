"""Declare the keys the control flow already depends on.

`edge_true` catches any exception and returns False, so an edge guarded on a key
nothing produces is not an error — it is an edge that is never taken. 52 guards
across 43 graphs were in that state: every `verify_failed and attempts < 3` retry,
every `<node>_failed` compensator, every `revision_requested` review loop. They
were dead, and every golden case passed anyway because the fixtures supply the key
by hand. Only a live run reaches the guard with a blackboard the model wrote.

v1.7 found exactly this for `attempts` — "48 edge guards across the registry read
it and nothing produced it" — and fixed that one name by publishing it from the
runtime. The hole was left open for every other guard key.

Two causes, and the second one is mine:

1. **Never declared.** `verify_failed`, `revision_requested`, `rejected` and the
   `<node>_failed` signals were a convention nobody wrote down. The node whose
   outcome the guard describes now declares the flag.

2. **Removed by the v1.8 contract rewrite.** Replacing self-graded contracts
   deleted flags that were ALSO routing guards — `exploit_blocked`,
   `impact_cleared`, `suite_green`, `attacker_exhausted`, `reconciled`,
   `milestones_covered`. Dropping them from the CONTRACT was right; dropping them
   from the node's OUTPUTS disabled the graph's second half.

That distinction is the point, and it is worth stating in the spec's terms: a
model-written flag may drive control flow, it just may not be the thing the
contract checks. Routing on a model's judgement is what a router IS. Grading a
model on its own judgement is what v1.8 refuses.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import iter_graphs, load
from agenticgraphs.validate import _flow_names


def _guard_sources(doc: dict) -> dict[str, str]:
    """Missing guard key -> the node that should declare it.

    The source is the edge's own origin: `verify_failed` on `verify->work` is a
    fact about how `verify` went, and `cutover_failed` on `cutover->undo-cutover`
    is a fact about `cutover`. An approval contract's keys belong to whatever
    feeds the gate.
    """
    produced = {o for n in doc.get("nodes", []) for o in _out_names(n)}
    produced |= set((doc.get("state") or {}).get("inputs") or [])
    want: dict[str, str] = {}
    for e in doc.get("edges", []):
        for name in _flow_names(e.get("when") or "") - produced:
            want.setdefault(name, e["from"])
    incoming = {e["to"]: e["from"] for e in doc.get("edges", [])}
    for n in doc.get("nodes", []):
        contract = (n.get("approval") or {}).get("contract", "")
        for name in _flow_names(contract) - produced:
            want.setdefault(name, incoming.get(n["id"], n["id"]))
    return want


def _out_names(node: dict) -> set[str]:
    return {o if isinstance(o, str) else next(iter(o)) for o in (node.get("outputs") or [])}


def main() -> int:
    fixed = graphs = 0
    for gpath in iter_graphs():
        doc = load(gpath)
        want = _guard_sources(doc)
        if not want:
            continue
        for name, node_id in want.items():
            node = next((n for n in doc["nodes"] if n["id"] == node_id), None)
            if node is None:
                continue
            outs = list(node.get("outputs") or [])
            # Declared `bool`, so the shape lint tells a routing flag from a value
            # and `_lint_self_graded` can keep exempting the latter.
            outs.append({name: "bool"})
            node["outputs"] = outs
            fixed += 1
        graphs += 1
        gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    print(f"declared {fixed} guard keys across {graphs} graphs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
