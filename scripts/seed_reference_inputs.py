"""Give the router cases a real reference, so their contract can actually fail.

v1.8 replaced six self-graded router contracts with a comparison: the branch emits
a decision, the verifier emits what the caller-supplied reference says it should
have been, and the assert compares them. The migration seeded those inputs with a
placeholder — `"<ownership_map supplied by the caller>"` — and the first live
recording showed exactly what that costs:

    branch-complex: {assigned_team: backend-infrastructure}
    verify:         {expected_team: backend-infrastructure}   -> PASS

With nothing to read, a model writes the same value into both fields and the
contract holds vacuously. That is the weakness the comparison was designed with —
"still satisfiable by a model that makes both equal" — and a placeholder guarantees
it every time. The comparison only bites when `expected_*` has a source.

So each router gets a real reference table and a goal naming a subject that
appears in it, plus a second case whose subject routes somewhere the obvious guess
does not. A contract that cannot fail is not a contract, and a fixture that cannot
fail does not test one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import cases_path

# graph -> {input key: reference table}, then per-case (goal, correct answer)
REFERENCES: dict[str, dict] = {
    "incident-triage-router": {
        "key": "ownership_map",
        "table": {"checkout": "payments-oncall", "search": "discovery-oncall",
                  "image-resize": "platform-oncall", "billing": "payments-oncall"},
        "field": "team",
        "cases": [
            ("the checkout 5xx page, against the 2026-Q3 ownership map", "payments-oncall"),
            # `image-resize` sounds like a media problem and is owned by platform.
            # A model guessing from the name gets this wrong, which is the point.
            ("the image-resize latency page, against the 2026-Q3 ownership map",
             "platform-oncall"),
        ],
    },
    "ticket-triage-swarm": {
        "key": "ownership_map",
        "table": {"refund not received": "billing-tier2", "cannot log in": "identity-tier1",
                  "invoice wrong amount": "billing-tier2", "app crashes on upload": "mobile-tier2"},
        "field": "queue",
        "cases": [
            ("the ticket 'refund not received', against the queue ownership map",
             "billing-tier2"),
            ("the ticket 'cannot log in', against the queue ownership map", "identity-tier1"),
        ],
    },
    "anomaly-investigation": {
        "key": "holdout_labels",
        "table": {"friday-signup-dip": "seasonal", "null-spike-2026-08-12": "data-bug",
                  "eu-latency-step": "real-change"},
        "field": "class",
        "cases": [
            ("the friday-signup-dip anomaly, against the labelled holdout", "seasonal"),
            # A null spike looks like a real change until you check the pipeline.
            ("the null-spike-2026-08-12 anomaly, against the labelled holdout", "data-bug"),
        ],
    },
    "clinical-literature-triage": {
        "key": "validated_labels",
        "table": {"PMID-30011": "1b", "PMID-30012": "2b", "PMID-30013": "4"},
        "field": "evidence_level",
        "cases": [
            ("PMID-30011, against the validated evidence-level sample", "1b"),
            # A large, confident cohort study is still level 2b.
            ("PMID-30012, against the validated evidence-level sample", "2b"),
        ],
    },
    "returns-triage": {
        "key": "policy_table",
        "table": {"arrived damaged": "refund", "changed mind, 40 days": "reject",
                  "wrong size": "exchange", "third return this month": "fraud-review"},
        "field": "disposition",
        "cases": [
            ("return R-55910, reason 'arrived damaged', against the 2026 returns policy",
             "refund"),
            # 40 days is outside the window even though the reason is sympathetic.
            ("return R-55911, reason 'changed mind, 40 days', against the 2026 returns policy",
             "reject"),
        ],
    },
    "phishing-triage": {
        "key": "labeled_corpus",
        "table": {"invoice-from-known-vendor": "benign",
                  "password-expiry-lookalike-domain": "phish",
                  "ceo-gift-card-request": "phish"},
        "field": "verdict",
        "cases": [
            ("the reported email 'invoice-from-known-vendor', against the labelled corpus",
             "benign"),
            ("the reported email 'password-expiry-lookalike-domain', against the labelled "
             "corpus", "phish"),
        ],
    },
}


def main() -> int:
    n = 0
    for name, spec in REFERENCES.items():
        cpath = cases_path(name)
        data = yaml.safe_load(cpath.read_text())
        key, table, field = spec["key"], spec["table"], spec["field"]
        for case, (goal, correct) in zip(data["cases"], spec["cases"], strict=True):
            case["goal"] = goal
            case.setdefault("inputs", {})[key] = table
            for nid in list(case["node_outputs"]):
                if nid.startswith("branch-"):
                    case["node_outputs"][nid] = {f"assigned_{field}": correct}
                elif nid == "verify":
                    case["node_outputs"][nid] = {
                        f"assigned_{field}": correct, f"expected_{field}": correct,
                        "output": {f"assigned_{field}": correct,
                                   f"expected_{field}": correct},
                    }
            n += 1
        cpath.write_text(yaml.safe_dump(data, sort_keys=False, width=100))
    print(f"seeded {n} router cases with a real reference table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
