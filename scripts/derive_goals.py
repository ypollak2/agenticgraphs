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
from agenticgraphs.registry import ROOT, SPEC_VERSION, cases_path, iter_graphs, load

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
# ---------------------------------------------------------------- v1.8 backfill
#
# Until v1.8 `needs_goal` asked whether a graph had declared `state.inputs`, so
# 52 graphs that declared nothing were held to nothing — they opened on an empty
# blackboard and a model invented a subject to answer about. Declaring nothing is
# not a defence; it is the maximal form of the gap, the same reasoning
# `validate.unconnected_keys` already applies to asserted keys.
#
# Each entry was drafted then reviewed against one rule: a goal names what the
# CALLER supplies, never what the graph produces. The draft failed that rule on
# roughly fifteen of these — "the quiz questions and answer keys" is the output
# of `quiz-generation-verified`, not its input — so every line below is the
# reviewed form.
GOALS.update({
    "meeting-to-actions": ("the meeting transcript to convert and the team it belongs to", "the 2026-08-14 platform sync transcript, for the infra team"),
    "policy-compliance-check": ("the internal documents to check and the policy set to check them against", "the vendor onboarding runbook, against InfoSec policy v4"),
    "rfp-response-assembler": ("the RFP to answer and the knowledge base to answer it from", "the Acme Health RFP, answered from the 2026 solutions library"),
    "blog-production-pipeline": ("the content brief to develop and the audience it targets", "the 'observability for small teams' brief, for platform engineers"),
    "localization-pipeline": ("the source content to translate and the locales to translate it into", "the onboarding guide, into de-DE, ja-JP and pt-BR"),
    "seo-optimization-loop": ("the page to optimize and the queries it should rank for", "/pricing, for 'agent workflow pricing'"),
    "book-editing-pipeline": ("the manuscript to edit and the house style it must follow", "the 90k-word Ridgeline draft, against the Kestrel style guide"),
    "podcast-production-pipeline": ("the episode transcript to work from and the show it belongs to", "episode 112 of Systems People"),
    "screenplay-coverage": ("the screenplay to cover and the market it is being read for", "the 104-page Longwater draft, for a mid-budget indie slate"),
    "ux-research-synthesis": ("the interview notes to synthesize and the research question behind them", "12 onboarding interviews, on why trial users stall at step 3"),
    "escalation-summarizer": ("the support thread to summarize and the tier receiving it", "ticket 84120, escalating to tier 3"),
    "kb-article-generator": ("the resolved ticket to write up and the audience for the article", "ticket 79004, written for self-serve customers"),
    "sales-call-scorer": ("the call transcript to score and the rubric to score it against", "the Northwind discovery call, against the MEDDIC rubric"),
    "ticket-triage-swarm": ("the tickets to triage and the queue ownership map to route by", "the overnight queue, against the 2026-Q3 ownership map"),
    "ab-test-analysis": ("the experiment's raw data and the effect the analysis claims", "experiment checkout-v3, claimed +2.1% conversion"),
    "data-quality-audit": ("the dataset to profile and the quality rules it must satisfy", "the customers table, against the CDM completeness rules"),
    "etl-pipeline-builder": ("the source and destination systems and the transformation the pipeline owes", "Stripe events into the warehouse, daily revenue by plan"),
    "schema-migration-saga": ("the current schema, the target schema, and the table that must stay live", "orders v3 to v4, keeping orders readable throughout"),
    "sql-generation-verified": ("the question to answer in SQL and the schema to answer it against", "monthly active accounts by plan, against the warehouse schema"),
    "alert-noise-reduction": ("the alert history to cluster and the window it covers", "the last 30 days of paging alerts"),
    "deploy-canary-verifier": ("the canary release to watch and the metrics that decide promotion", "api v2.14.0 at 5%, on p99 latency and 5xx rate"),
    "postmortem-writer": ("the incident timeline to write up and the severity it was declared at", "INC-2291, declared SEV2"),
    "runbook-executor": ("the runbook to execute and the environment to execute it in", "the certificate rotation runbook, in staging"),
    "quiz-generation-verified": ("the source material to quiz on and the level of the learners", "chapter 4 on photosynthesis, for year 9"),
    "rubric-grading-swarm": ("the submissions to grade and the rubric to grade them against", "34 essays, against the AP argumentation rubric"),
    "essay-feedback-critic": ("the essay to critique and the assignment brief it answers", "a 1200-word essay, against the 'causes of the Dust Bowl' brief"),
    "expense-audit-swarm": ("the expense reports to audit and the policy that governs them", "August EMEA reports, against the 2026 travel policy"),
    "kyc-document-processing": ("the customer documents to process and the jurisdiction's KYC requirements", "a UK sole-trader onboarding pack, under FCA rules"),
    "portfolio-rebalance-review": ("the rebalance proposal to review and the mandate it must satisfy", "the Q3 proposal, against the balanced-growth mandate"),
    "clinical-literature-triage": ("the papers to triage and the evidence hierarchy to rank them by", "142 new papers on SGLT2 inhibitors, by GRADE"),
    "medical-coding-audit": ("the assigned codes to audit and the clinical documentation behind them", "the July inpatient DRG assignments and their charts"),
    "differential-diagnosis-ensemble": ("the presenting case and the history available to reason from", "a 54-year-old with acute dyspnoea and a cardiac history"),
    "jd-drafting-critic": ("the role to describe and the level and team it sits in", "a staff platform engineer on the infra team"),
    "onboarding-plan-builder": ("the new hire's role and the team they are joining", "a senior data analyst joining growth"),
    "contract-redline-pipeline": ("the contract to redline and the playbook of acceptable positions", "the Meridian MSA, against the 2026 commercial playbook"),
    "regulatory-filing-check": ("the filing to check and the regulation it is filed under", "the Q2 10-Q, under SEC reporting rules"),
    "returns-triage": ("the return request to route and the policy table that governs it", "return R-55910, against the 2026 returns policy"),
    "supplier-risk-monitor": ("the supplier portfolio to monitor and the risk thresholds that matter", "the 240 tier-1 suppliers, on single-source and concentration"),
    "threat-intel-digest": ("the feeds to digest and the estate the brief is written for", "this week's CISA and vendor feeds, for a Kubernetes estate"),
    "phishing-triage": ("the reported email to classify and the organisation's sender baseline", "a reported invoice email, against known-good senders"),
    "soc-alert-investigation": ("the alert to investigate and the telemetry available to investigate it", "an impossible-travel alert, with 30 days of auth logs"),
    "red-team-blue-team-hardening": ("the system to harden and the threat model to harden it against", "the public API, against an authenticated-tenant attacker"),
    "vuln-prioritization": ("the vulnerabilities to rank and the asset map that gives them exposure", "the weekly scanner output, against the prod asset map"),
    "bug-triage-and-fix": ("the bug report to fix and the repository it reproduces in", "issue 481, reproducing in the checkout service"),
    "legacy-refactor": ("the code to refactor and the test suite that must stay green", "the billing module, keeping tests/billing green"),
    "performance-optimization": ("the workload to optimize and the latency or throughput target", "the search endpoint, to p95 under 200ms"),
    "release-notes-generation": ("the merged pull requests to summarize and the release they ship in", "the 41 PRs merged since v2.13, for v2.14.0"),
    "test-suite-generation": ("the module to test and the coverage or mutation bar it must clear", "the pricing module, to 85% mutation score"),
    "docs-code-sync-audit": ("the documentation to audit and the codebase it describes", "docs/ against src/ at the current HEAD"),
    "competitive-intelligence": ("the competitors to profile and the decision the brief informs", "three workflow vendors, informing Q4 positioning"),
    "literature-review-swarm": ("the research question to review and the inclusion criteria for screening", "does spaced repetition improve retention, RCTs since 2015"),
    "citation-integrity-audit": ("the document whose citations to verify and the sources it cites", "the systematic review draft and its 96 references"),
})

# The last eleven. Each declares no `state.inputs` at all, which is precisely why
# they were invisible to the v1.7 test — see `needs_goal`.
GOALS.update({
    "anomaly-investigation": ("the metric anomaly to investigate and the window it appeared in", "the 2026-08-12 spike in signup latency, over the prior 14 days"),
    "incident-triage-router": ("the incident to route and the on-call ownership map to route it by", "the checkout 5xx page, against the 2026-Q3 ownership map"),
    "verifier-swarm": ("the goal to decompose and the command that proves it done", "make tests/integration pass; proven by `pytest tests/integration`"),
    "earnings-call-digest": ("the earnings call to digest and the prior guidance to compare against", "the Q2 2026 call, against the guidance given in Q1"),
    "adverse-event-scanner": ("the reports to scan and the product whose safety signal matters", "the August case reports, for compound RX-114"),
    "ediscovery-triage": ("the document set to triage and the matter that defines relevance", "the custodian mailboxes, for the Meridian breach-of-contract matter"),
    "license-compliance-scan": ("the dependency set to scan and the licence policy it must satisfy", "the production lockfile, against the no-copyleft policy"),
    "cost-routed-research": ("the research question to answer and the confidence bar an answer must clear", "what drives churn in usage-based pricing, cited to primary sources"),
    "fact-check-pipeline": ("the claims to check and the sources they may be checked against", "the twelve claims in the launch post, against primary sources"),
    "code-review-pipeline": ("the change to review and the repository it lands in", "PR 812 in the payments service"),
    "dependency-upgrade": ("the dependencies to upgrade and the suite that must stay green", "the minor-version bumps in the lockfile, keeping tests/ green"),
})

TRIGGER_EXEMPT = {
    # A graph whose firing event carries the subject is exempt on its own
    # schedule and required on manual invocation. Without this it could never
    # fire: the goal gate would refuse before any node was scheduled.
    "self-healing-ci", "supplier-risk-monitor", "alert-noise-reduction",
    "deploy-canary-verifier", "dependency-upgrade", "docs-code-sync-audit",
}


def needs_goal(doc: dict) -> bool:
    """Every graph needs a goal. v1.7 asked whether one had declared `state.inputs`.

    That test excused the 52 graphs that declared nothing — and a graph declaring
    no inputs is not a graph that needs no subject, it is a graph that never said
    so. They opened on an empty blackboard, and a model handed an empty board
    invents a plausible subject and answers about that.
    """
    return True


def migrate_graph(doc: dict) -> bool:
    name = doc["name"]
    if not needs_goal(doc) or name not in GOALS:
        return False
    description, _ = GOALS[name]
    goal = {"required": True, "description": description}
    if name in TRIGGER_EXEMPT:
        goal["supplied_by_trigger"] = True
    if doc.get("goal") == goal and "goal" in ((doc.get("state") or {}).get("inputs") or []):
        return False
    doc["goal"] = goal
    # The requirement is enforced against a blackboard key, so the key must be
    # declared as supplied at entry — that is what the first lint checks.
    state = doc.setdefault("state", {})
    inputs = list(state.get("inputs") or [])
    if "goal" not in inputs:
        state["inputs"] = ["goal", *inputs]
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
