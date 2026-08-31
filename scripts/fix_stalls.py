"""Give every graph a way to say the work did not get done.

Ten graphs share one shape at their decision point:

    confirm -> mitigate   when: not impact_cleared and attempts < 3
    confirm -> postmortem when: impact_cleared

Retry while it is failing and you have attempts left; go forward when it worked.
**Nothing covers the third case** — still failing, attempts exhausted. There is no
edge, so the run stops: not failed, not escalated, just stopped. The contract then
reports `AttributeError` for a key produced by a node that was never reached, which
is how nine graphs in the first v1.8 sweep misdescribed their own outcome.

Two of the ten do not even have the retry. `rights-check -> publish when
rights_clear` is the whole of that node's forward flow, so an unclear rights
position stalls the graph immediately.

`regulatory-filing-lifecycle` shows why this matters beyond tidiness: it reconciles
three times against figures it cannot balance, exhausts the bound, and stops. The
filing is neither made nor formally abandoned — and "we could not reconcile" is the
outcome a finance workflow most needs to be able to record.

The fix is one escalation terminal per graph, reached by the complement of the two
existing conditions. It is deliberately a real node with a rubric rather than a
dangling edge: escalating means handing a human the state and the reason, and a
graph that can only succeed has not modelled its own job.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import cases_path, load

# graph -> (stall node, escalation node id, guard for the uncovered case, criteria)
STALLS: list[tuple[str, str, str, str, str]] = [
    ("incident-lifecycle", "confirm", "escalate-incident",
     "not impact_cleared and attempts >= 3",
     "The incident is handed on with the mitigations tried and the signal that is "
     "still out of bounds. An incident nobody could clear is escalated, not closed."),
    ("vuln-remediation-lifecycle", "prove", "escalate-vuln",
     "not exploit_blocked and attempts >= 3",
     "The vulnerability is escalated with every patch attempted and the "
     "proof-of-concept still succeeding. Nothing is disclosed on this path."),
    ("framework-migration", "integrate", "escalate-migration",
     "not suite_green and attempts >= 3",
     "The migration halts with the failing slice named and the suite output "
     "attached, so the next attempt starts from what broke rather than from zero."),
    ("regulatory-filing-lifecycle", "reconcile", "abandon-filing",
     "not reconciled and attempts >= 3",
     "The filing is formally abandoned with the unreconciled variance recorded. A "
     "filing that cannot be reconciled must be visibly not-filed, never silently "
     "unfiled."),
    ("hiring-lifecycle", "interview", "escalate-hiring",
     "len(scorecards) < 3 and attempts >= 2",
     "The role is escalated with the shortlist and the scorecards actually "
     "collected. Fewer than three assessments is a decision that cannot be made, "
     "not a decision to reject."),
    ("performance-cycle-summarizer", "bias-check", "escalate-review",
     "len(bias_flags) > 0 and attempts >= 2",
     "The review goes to a human with the surviving bias flags named. A summary "
     "that could not be de-biased must not be published as if it had been."),
    ("book-editing-pipeline", "copy-edit", "escalate-manuscript",
     "len(style_violations) > 0 and attempts >= 2",
     "The manuscript returns to the editor with the violations that survived "
     "copy-editing, rather than reaching an author sign-off it has not earned."),
    ("contract-lifecycle", "risk-assess", "escalate-contract",
     "residual_risk > medium and attempts >= 2",
     "The contract escalates with the residual risk that redlining could not "
     "reduce. Risk above appetite is a decision for counsel, not a blocked graph."),
    ("product-listing-pipeline", "claim-check", "escalate-listing",
     "len(unsupported_claims) > 0 and attempts >= 2",
     "The listing is held with the claims that could not be substantiated. An "
     "unsupported product claim is a regulatory exposure, not a copy defect."),
    ("product-listing-pipeline", "policy-check", "escalate-listing",
     "len(policy_violations) > 0",
     "The listing is held with the marketplace policy it breaches. This node had "
     "no failure path at all: a violation simply stopped the graph."),
    ("podcast-production-pipeline", "rights-check", "escalate-rights",
     "not rights_clear",
     "The episode is held with the clips whose licensing could not be confirmed. "
     "This node had no failure path at all: unclear rights stopped the graph, "
     "which looks identical to rights being clear."),
]


def main() -> int:
    added = 0
    for name, src, esc_id, guard, criteria in STALLS:
        gpath = find_graph(name)
        doc = load(gpath)
        if not any(n["id"] == esc_id for n in doc["nodes"]):
            doc["nodes"].append({
                "id": esc_id, "speciality": "escalator", "abilities": ["escalate"],
                "inputs": [], "outputs": [{"escalated": "bool"}, "escalation_reason"],
                "criteria": criteria,
            })
        if not any(e["from"] == src and e["to"] == esc_id for e in doc["edges"]):
            doc["edges"].append({"from": src, "to": esc_id, "when": guard})
            added += 1
        gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))

        cpath = cases_path(name)
        data = yaml.safe_load(cpath.read_text())
        for case in data["cases"]:
            case["node_outputs"].setdefault(esc_id, {})
        cpath.write_text(yaml.safe_dump(data, sort_keys=False, width=100))
    print(f"added {added} escalation edges across {len({s[0] for s in STALLS})} graphs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
