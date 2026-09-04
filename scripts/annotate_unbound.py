"""Declare, on every node the new lints refuse, what was already true.

    uv run python scripts/annotate_unbound.py

R3-04 (`_lint_unbound`) and R3-05 (`_lint_retry_reissue`) from the 2026-09-04
audit refuse a node whose execute/world-write ability has no binding, and a node
that retries a non-idempotent ability, unless the node says so. Every graph in
the registry was doing both silently. This writes the declaration that matches
current behaviour — `unbound_ok` names the narrated abilities, `reissue_effects`
accepts the repeated effect — so the gap is on the record per node instead of
implicit everywhere. It does not make any node safer; it makes the count visible
(77 graphs at the time of writing) so binding work can burn it down.
Idempotent; only touches nodes the lints would fail.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import iter_graphs, iter_yaml, load
from agenticgraphs.validate import _bindable


def main() -> int:
    abilities = {load(p)["name"]: load(p) for p in iter_yaml("abilities")}
    bindable = _bindable(abilities)

    def world(a: dict) -> bool:
        risk = a.get("risk", "read")
        return risk == "execute" or (risk == "write" and a.get("idempotent", True) is False)

    touched = 0
    for gpath in iter_graphs():
        doc = load(gpath)
        changed = False
        for n in doc.get("nodes", []):
            if n.get("kind") in ("subgraph", "human"):
                continue
            narrated = sorted(a for a in n.get("abilities") or []
                              if a in abilities and world(abilities[a]) and a not in bindable)
            if narrated and not n.get("unbound_ok"):
                n["unbound_ok"] = (
                    f"narrated: {', '.join(narrated)} has no binding in this runtime; the effect "
                    "is the model's account of it until the ability is bound (audit 2026-09-04, Q1)"
                )
                changed = True
            r = n.get("retries") or {}
            risky = [a for a in n.get("abilities") or []
                     if a in abilities and abilities[a].get("idempotent", True) is False]
            if r.get("max") and risky and not r.get("reissue_effects"):
                r["reissue_effects"] = True
                changed = True
        if changed:
            gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
            touched += 1
    print(f"annotated {touched} graphs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
