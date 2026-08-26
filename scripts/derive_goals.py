"""Declare a required goal on every graph that cannot know its subject without one.

`state.inputs` has existed since v1.1 and named, per graph, exactly what the caller
must bring at entry. Nothing ever supplied it: `run_graph` opened with `bb = {}`, so
the linter vouched for values that never arrived and every graph began work not
knowing what it was working on. A model handed an empty board invents a plausible
subject and answers about that — a well-typed answer to a question nobody asked.

Which graphs need a goal is therefore not a judgement call; it is already recorded.
A graph declares `state.inputs` exactly when its entry needs something no node
produces. This reads that declaration and makes it enforceable.

Two graphs (`self-healing-ci`, `supplier-risk-monitor`) declare both `state.inputs`
and `triggers`. Their firing event carries the subject, so they are marked
`supplied_by_trigger` — required on manual invocation, exempt on their own schedule.
Without that they could never fire.

**No assert is ever modified.** The cheap way to make a contract easier is to weaken
what it checks; this script only adds a `goal` block, one `state.inputs` entry, and a
goal to each golden case.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import ROOT, SPEC_VERSION, cases_path, iter_graphs, load  # noqa: E402

# name -> (what the caller must state, a concrete instance for the golden cases)
#
# Derived from each graph's own `state.inputs` key and description, then reviewed —
# the same derive-then-review loop v1.4 used, which is why it changed zero asserts.
# The description is shown verbatim when the graph refuses, so it must read as an
# instruction to the caller, not as a field name.
GOALS: dict[str, tuple[str, str]] = {
    "invoice-reconciliation": (
        "the invoice batch to reconcile and the period it covers",
        "reconcile the March 2026 supplier invoice batch against POs and receipts"),
    "procurement-lifecycle": (
        "the requirement to source, with its budget envelope and award deadline",
        "source a data-warehouse vendor under a 120k budget, award by Q4"),
    "vendor-comparison-matrix": (
        "the vendors to compare and the decision the matrix must inform",
        "compare Snowflake, BigQuery and Redshift for our warehouse migration"),
    "book-editing-pipeline": (
        "the manuscript to edit and the editorial brief it must meet",
        "edit the 90k-word literary novel manuscript to submission standard"),
    "podcast-production-pipeline": (
        "the recording to publish and the episode's intended audience",
        "publish episode 42 of the founders interview series for a technical audience"),
    "screenplay-coverage": (
        "the screenplay to cover and the mandate it is being read against",
        "cover the 110-page contained sci-fi thriller against a low-budget mandate"),
    "sales-call-scorer": (
        "the call transcript to score and the rubric it is judged on",
        "score the Acme discovery call against the MEDDIC rubric"),
    "schema-migration-saga": (
        "the source schema and the target shape it must reach",
        "migrate the orders schema to the normalized v3 shape without downtime"),
    "incident-lifecycle": (
        "the alert to work and what 'resolved' means for this service",
        "work the checkout-latency page; resolved means p99 back under 400ms"),
    "self-healing-ci": (
        "the red pipeline run to diagnose and repair",
        "repair the failing nightly build on main"),
    "regulatory-filing-lifecycle": (
        "the filing period and the regime being filed under",
        "file Q1 2026 under the SEC regime with reconciled figures"),
    "clinical-protocol-lifecycle": (
        "the study question the protocol must answer",
        "draft a phase II protocol for drug X in treatment-resistant patients"),
    "differential-diagnosis-ensemble": (
        "the case to work up and the question the clinician needs answered",
        "work up the 54-year-old with intermittent chest pain and normal troponin"),
    "trial-eligibility-screener": (
        "the trial to screen against and the cohort to screen",
        "screen the oncology cohort against NCT-12345 eligibility criteria"),
    "hiring-lifecycle": (
        "the role to fill and what a successful hire must be able to do",
        "hire a senior backend engineer who can own our payments service"),
    "onboarding-plan-builder": (
        "the role and team the 30/60/90 plan is for",
        "build a 30/60/90 plan for a staff data engineer joining the platform team"),
    "performance-cycle-summarizer": (
        "the review cycle and the person it covers",
        "summarize the H1 2026 cycle for a senior engineer on the infra team"),
    "contract-lifecycle": (
        "the contract to review and the risk posture to hold it to",
        "review the Acme MSA under our standard enterprise risk posture"),
    "gdpr-data-audit": (
        "the systems in scope and the lawful-basis question being answered",
        "audit personal data across CRM, billing and support for lawful basis"),
    "product-listing-pipeline": (
        "the products to list and the marketplace policy that governs them",
        "list the spring hardware line on Amazon under its claims policy"),
    "supplier-risk-monitor": (
        "the supplier portfolio to score",
        "score the tier-1 electronics supplier portfolio for concentration risk"),
    "prompt-graph-optimization": (
        "the graph to optimize and the metric that decides a winner",
        "optimize the support-triage graph for accuracy on the held-out set"),
    "compliance-evidence-collector": (
        "the control framework to evidence and the audit period",
        "collect SOC 2 Type II evidence for the 2026 audit period"),
    "forensic-investigation-blackboard": (
        "the incident to investigate and the question the investigation must settle",
        "investigate the S3 exfiltration alert; settle whether data left the account"),
    "red-team-blue-team-hardening": (
        "the target to harden and what counts as a successful bypass",
        "harden the auth service; a bypass is any unauthenticated admin action"),
    "vuln-remediation-lifecycle": (
        "the vulnerability to remediate and the affected estate",
        "remediate CVE-2026-1234 across the payment services estate"),
    "architecture-decision-tournament": (
        "the architecture decision to settle and the constraints any winner must meet",
        "settle sync vs async order processing under a 200ms p99 constraint"),
    "benchmark-driven-optimization-search": (
        "the repository to optimize and the benchmark that scores it",
        "optimize the parser repo against the throughput benchmark"),
    "feature-delivery-lifecycle": (
        "the feature to deliver and the repository to deliver it in",
        "add SSO login to the web app in the platform repo"),
    "flaky-test-reflexion": (
        "the test suspected of flaking and the stability bar it must clear",
        "stabilize test_checkout_timeout; it must go 3 consecutive greens"),
    "framework-migration": (
        "the codebase to port, its source framework and its target framework",
        "port the admin app from Flask to FastAPI in verifiable slices"),
}

# Their firing event carries the subject; the requirement is on manual invocation.
TRIGGER_EXEMPT = {"self-healing-ci", "supplier-risk-monitor"}


def needs_goal(doc: dict) -> bool:
    """A graph needs a goal exactly when its entry needs something no node produces."""
    return bool((doc.get("state") or {}).get("inputs"))


def migrate_graph(doc: dict) -> bool:
    name = doc["name"]
    if not needs_goal(doc) or name not in GOALS:
        return False
    description, _ = GOALS[name]
    goal = {"required": True, "description": description}
    if name in TRIGGER_EXEMPT:
        goal["supplied_by_trigger"] = True
    if doc.get("goal") == goal and "goal" in doc["state"]["inputs"]:
        return False
    doc["goal"] = goal
    # The requirement is enforced against a blackboard key, so the key must be
    # declared as supplied at entry — that is what the first lint checks.
    if "goal" not in doc["state"]["inputs"]:
        doc["state"]["inputs"] = ["goal"] + list(doc["state"]["inputs"])
    return True


def migrate_cases(name: str, root: Path) -> int:
    """Give every golden case a concrete goal, so the fixtures exercise the gate."""
    path = cases_path(name)
    if not path.exists():
        return 0
    data = yaml.safe_load(path.read_text())
    _, example = GOALS[name]
    changed = 0
    for case in data["cases"]:
        if case.get("goal") != example:
            case["goal"] = example
            changed += 1
    if changed:
        path.write_text(yaml.safe_dump(data, sort_keys=False, width=100))
    return changed


def main() -> int:
    graphs = cases = bumped = 0
    for gpath in iter_graphs():
        doc = load(gpath)
        changed = migrate_graph(doc)
        if changed:
            graphs += 1
        # One spec version across the registry, as every prior migration left it.
        # A split registry would mean `agr/v1.6` graphs existed, and v1.6 is the
        # version that arms the hard provenance lint — see registry.SPEC_VERSION.
        if doc.get("apiVersion") != SPEC_VERSION:
            doc["apiVersion"] = SPEC_VERSION
            bumped += 1
            changed = True
        if changed:
            gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
        # Cases are reconciled every run, not only when the graph changed. Gating
        # them on `changed` made the script non-idempotent: re-running it over an
        # already-migrated registry left the golden cases without goals, so every
        # case of every required graph would refuse.
        if doc["name"] in GOALS:
            cases += migrate_cases(doc["name"], ROOT)
    unmapped = sorted(
        load(g)["name"] for g in iter_graphs()
        if needs_goal(load(g)) and load(g)["name"] not in GOALS
    )
    print(f"goal declared on {graphs} graphs; {cases} golden cases given a goal; "
          f"{bumped} graphs bumped to {SPEC_VERSION}")
    if unmapped:
        print(f"UNMAPPED (declare state.inputs but have no goal text): {unmapped}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
