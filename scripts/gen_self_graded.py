"""Which graphs the self-graded lint refuses right now, written where CI can diff it.

    uv run python scripts/gen_self_graded.py     # writes reports/self-graded.json

`reports/self-graded.json` used to be a hand-banked snapshot with no generator:
it said 16 while `agr validate` found 0, because the asserts had been reworded
past the lint rather than fixed (2026-09-04 audit, D6-01). A number nothing
regenerates is a number nothing checks. This emits the lint's current verdict,
deterministically, so the file can only ever say what the code says.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import ROOT, SPEC_VERSION, iter_graphs, load
from agenticgraphs.validate import _lint_self_graded

OUT = ROOT / "reports" / "self-graded.json"


def main() -> int:
    flagged = {}
    for gp in iter_graphs():
        doc = load(gp)
        errs = _lint_self_graded(doc)
        if errs:
            flagged[doc["name"]] = errs
    report = {
        "armed_at": SPEC_VERSION,
        "generated_by": "scripts/gen_self_graded.py",
        "count": len(flagged),
        "graphs": {k: flagged[k] for k in sorted(flagged)},
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(flagged)} graphs flagged by _lint_self_graded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
