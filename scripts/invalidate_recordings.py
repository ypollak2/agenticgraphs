"""Mark every live recording as superseded by the v1.8 evaluation changes.

A recording is a measurement, and a measurement is only valid under the
conditions it was taken. Three v1.8 changes invalidate all 560 of them:

1. **The prompt leaked the answer.** Every node was told
   `Downstream assertions that must hold: [...]` and then scored on exactly those
   asserts. 31 of 117 asserts were a bare truthy read, and for 16 the key was
   declared as an output of the graph's own verifier. Those runs measured whether
   a model can echo a flag it was just shown.
2. **Sixteen contracts no longer exist.** The self-graded ones were replaced with
   cross-node comparisons and executable commands, so a recording against the old
   contract cannot be scored against the new one at all.
3. **Sampling was unpinned.** No seed, no temperature, provider defaults. The
   "same model, different answer" finding on 50 of 83 graphs mixed real graph
   fragility with sampling noise, and there is no way to separate them after
   the fact.

Deleting the files would be worse than keeping them: the counts they support are
quoted in the README and CHANGELOG, and a reader deserves to see what was
measured and why it no longer counts. So each recording is stamped rather than
removed, and every report that reads them says the evidence base is pending
re-recording instead of quoting a number it can no longer stand behind.

Re-record with `scripts/record_live.py` against a real endpoint. That run costs
money and is the one part of the v1.8 plan a checkout cannot do for itself.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import ROOT

SUPERSEDED = {
    "superseded_by": "agr/v1.8",
    "reason": (
        "recorded while the runner passed verification asserts into the node prompt, "
        "under unpinned sampling, and against contracts that v1.8 replaced. Not "
        "comparable to a v1.8 recording; re-record with scripts/record_live.py."
    ),
}


def main() -> int:
    n = 0
    for path in sorted(ROOT.glob("graphs/*/*/live/*.json")):
        doc = json.loads(path.read_text())
        if doc.get("superseded_by") == SUPERSEDED["superseded_by"]:
            continue
        doc.update(SUPERSEDED)
        path.write_text(json.dumps(doc, indent=2) + "\n")
        n += 1
    print(f"stamped {n} recordings as superseded by agr/v1.8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
