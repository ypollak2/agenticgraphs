"""Declare the two collections a membership test reads.

`c in output.criteria_grid` and `r.clinician_id in output.represented` both require
the right-hand side to be a collection, and neither declared a shape. The model
returned a string for each, and `in` on a string is a substring test — so the
assert did not fail loudly, it failed with
`TypeError: argument of type 'X' is not iterable` or, worse, quietly matched a
substring.

This is the same gap `declare_record_shapes.py` closed for ten graphs that iterate
records. It is separate because the failure mode differs: an undeclared list that
is *iterated* raises immediately, while an undeclared list that is *searched* can
silently return a wrong answer.

Two other graphs looked like this and are not: `license-compliance-scan` already
declares `packages: list[{spdx:any}]` and `adverse-event-scanner` already declares
`signals`. The model was told the shape and returned strings anyway. Those are
results about the model, not gaps in the contract, and they stay recorded as
failures.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import load

SHAPES = {
    "vendor-comparison-matrix": {"criteria_grid": "list"},
    "differential-diagnosis-ensemble": {"represented": "list"},
}


def main() -> int:
    n = 0
    for name, shapes in SHAPES.items():
        gpath = find_graph(name)
        doc = load(gpath)
        for node in doc["nodes"]:
            outs = []
            for o in node.get("outputs") or []:
                key = o if isinstance(o, str) else next(iter(o))
                if isinstance(o, str) and key in shapes:
                    outs.append({key: shapes[key]})
                    n += 1
                else:
                    outs.append(o)
            if outs:
                node["outputs"] = outs
        gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    print(f"declared {n} membership collections across {len(SHAPES)} graphs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
