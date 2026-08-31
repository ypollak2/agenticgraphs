"""Tell the model the record shape its contract quantifies over.

The v1.8 contract rewrite replaced verdict flags with checks over collections —
`all(m.invoice_id and m.po_id and m.receipt_id for m in output.matched)` instead of
`output.three_way_matched == true`. That is a better contract, and it was
incomplete: ten of those collections were declared as a bare output name, so the
prompt said "return `matched`" and the assert quietly required a list of records
with three named fields.

The first live run showed exactly what that costs. `qwen3-coder:30b` returned

    matched: 24

— a count, which is a perfectly reasonable reading of "return `matched`" — and the
assert died with `TypeError: 'int' object is not iterable`. That result measures
whether a model can guess an undocumented schema, not whether the workflow works.
It is the same defect as the leaked assert text, mirrored: there, the model was
told too much; here, too little.

`shapes` has existed since v1.5 and `_shapes.describe` already puts declarations
into the prompt verbatim. The declarations were simply never written for the keys
v1.8 introduced.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import cases_path, load

#: graph -> {output key: shape}. Each shape names exactly the fields its own
#: contract reads — no more, so the declaration cannot drift into wishful scope.
SHAPES: dict[str, dict[str, str]] = {
    "invoice-reconciliation": {
        "matched": "list[{invoice_id:any, po_id:any, receipt_id:any}]"},
    "vendor-comparison-matrix": {
        "matrix": "list[{criteria:list, vendor:any}]"},
    "podcast-production-pipeline": {
        "clearances": "list[{license_ref:any}]",
        "timestamps": "list[{start:int, end:int}]"},
    "incident-lifecycle": {
        "actions": "list[{owner:any, task:any}]"},
    "differential-diagnosis-ensemble": {
        "ranking": "list[{clinician_id:any}]"},
    "onboarding-plan-builder": {
        "plan_30_60_90": "list[{milestone:any}]",
        "access_requests": "list[{system:any, requested_on:any}]"},
    "contract-lifecycle": {
        "signatures": "list[{party:any, dated:any}]"},
    "supplier-risk-monitor": {
        "concentration": "list[{single_source:bool, supplier_count:int}]"},
    "red-team-blue-team-hardening": {
        "bypasses": "list[{mitigation_ref:any}]"},
    "feature-delivery-lifecycle": {
        "doc_changes": "list[{file:any, pr_url:any}]"},
}


#: The value an upstream node must produce for the shape it now declares. These
#: replace placeholder strings the original generator emitted — `"ranking-value"`
#: for a list of clinician rankings — which no shape had ever contradicted.
FIXTURES: dict[str, dict] = {
    "invoice-reconciliation": {
        "matched": [{"invoice_id": "INV-1", "po_id": "PO-1", "receipt_id": "GR-1"}]},
    "onboarding-plan-builder": {
        "plan_30_60_90": [{"milestone": "ship one PR"}],
        "access_requests": [{"system": "github", "requested_on": "2026-08-20"}]},
    "supplier-risk-monitor": {
        "concentration": [{"single_source": True, "supplier_count": 1}]},
    "differential-diagnosis-ensemble": {
        "ranking": [{"clinician_id": "c1"}, {"clinician_id": "c2"}]},
}


def _apply(outputs: list, shapes: dict[str, str]) -> list:
    """Replace a bare name with a `{name: shape}` mapping, keeping order."""
    out = []
    for o in outputs:
        name = o if isinstance(o, str) else next(iter(o))
        if isinstance(o, str) and name in shapes:
            out.append({name: shapes[name]})
        else:
            out.append(o)
    return out


def main() -> int:
    n = 0
    for name, shapes in SHAPES.items():
        gpath = find_graph(name)
        doc = load(gpath)
        for node in doc["nodes"]:
            outs = node.get("outputs")
            if not outs:
                continue
            new = _apply(outs, shapes)
            if new != outs:
                node["outputs"] = new
                n += 1
        gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
        # The golden cases must satisfy the shape they now declare, or the
        # fixtures vouch for a structure no run produces — which is the same fault
        # as the contract not stating it. Four were placeholder strings
        # (`"ranking-value"`) from the original generator, and the shape lint found
        # every one the moment a shape existed to check them against.
        cpath = cases_path(name)
        data = yaml.safe_load(cpath.read_text())
        for case in data["cases"]:
            for out in case["node_outputs"].values():
                if not isinstance(out, dict):
                    continue
                for key, value in FIXTURES.get(name, {}).items():
                    if key not in out:
                        continue
                    cur = out[key]
                    # Wrong type, or right type with the wrong fields. The second
                    # case is the subgraph child's fixture — `[{"inv": 1}]` under
                    # `auto-match.verify` — which looked like a list and satisfied
                    # nothing the parent's contract reads.
                    needed = set(value[0]) if value and isinstance(value[0], dict) else set()
                    ok = isinstance(cur, list) and all(
                        isinstance(r, dict) and needed <= set(r) for r in cur
                    )
                    if not ok:
                        out[key] = value
        cpath.write_text(yaml.safe_dump(data, sort_keys=False, width=100))
    print(f"declared record shapes on {n} nodes across {len(SHAPES)} graphs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
