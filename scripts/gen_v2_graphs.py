"""Generate the AGR v1.1 composite graphs and their golden cases.

Unlike `gen_graphs.py` (which stamps 3-node motif templates), every graph here is
a *composite*: an explicit phase list, a declared I/O contract per phase, and one
of the five v1.1 motifs. Phases marked `sub=<ref>` are not re-authored — they
reference an existing registry graph and are inlined at load time.

Fixtures are derived mechanically from each phase's declared `outputs` plus an
explicit `final` block, so a generated graph's golden case passes by construction
rather than by hand-tuning.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.subgraphs import expand

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- phase helper


def P(pid, spec, abil, outs, *, ins=(), sub=None, kind=None, join=None):
    """One phase. `sub` makes it a subgraph reference instead of a leaf agent."""
    n = {"id": pid, "speciality": "supervisor" if sub else spec}
    if sub:
        n["kind"] = "subgraph"
        n["ref"] = sub
    else:
        n["abilities"] = list(abil)
        if kind:
            n["kind"] = kind
    if ins:
        n["inputs"] = list(ins)
    if outs:
        n["outputs"] = list(outs)
    if join:
        n["join"] = join
    return n


def GATE(pid, contract, ins, outs=("signed_off",)):
    return {
        "id": pid, "speciality": "approver", "kind": "human", "abilities": ["approve"],
        "inputs": list(ins), "outputs": list(outs),
        "approval": {"contract": contract, "timeout": "24h", "on_timeout": "escalate"},
    }


# ------------------------------------------------------------------- the graphs
# Each entry: (name, domain, motif, phases, edges, checks, final, contract, steps)
# `edges` uses (from, to) or (from, to, when) or (from, to, when, kind).

G: list[dict] = []


def g(name, domain, motif, summary, phases, edges, checks, final, contract, steps=40,
      state_inputs=(), seed=None):
    """Register a composite.

    `final` is the `output` object the terminal node emits. `seed` pins specific
    blackboard keys that *routing guards* depend on — the stub heuristic can pick
    a plausible type but not a value that steers a branch (a gate contract needs
    `signed_off: true`, not the string `"signed_off-value"`).
    """
    G.append({"name": name, "domain": domain, "motif": motif, "summary": summary, "phases": phases,
                  "edges": edges, "checks": checks, "final": final, "contract": contract, "steps": steps,
                  "state_inputs": list(state_inputs), "seed": dict(seed or {})})


# ---- Tier A: flagship composites -------------------------------------------

g("incident-lifecycle", "devops-sre", "lifecycle",
  "Detect, triage, mitigate and prove an incident closed, then write the postmortem and file the actions.",
  [P("detect", "analyst", ["analyze"], ["signal", "blast_radius"], ins=["alert"]),
   P("triage", None, None, ["severity", "owner"], ins=["signal"], sub="devops-sre/incident-triage-router"),
   P("mitigate", "sre", ["run_command"], ["mitigation", "mitigated"], ins=["severity"]),
   P("confirm", "verifier", ["run_command"], ["impact_cleared"], ins=["mitigation"], kind="verifier"),
   P("postmortem", None, None, ["postmortem"], ins=["mitigation"], sub="devops-sre/postmortem-writer"),
   P("action-items", "planner", ["decompose_goal"], ["actions"], ins=["postmortem"])],
  [("detect", "triage"), ("triage", "mitigate"), ("mitigate", "confirm"),
   ("confirm", "mitigate", "not impact_cleared and attempts < 3"),
   ("confirm", "postmortem", "impact_cleared"), ("postmortem", "action-items")],
  [("impact is cleared before the incident is written up", "output.impact_cleared == true"),
   ("every postmortem produces at least one owned action", "len(output.actions) >= 1")],
  {"impact_cleared": True, "actions": [{"owner": "sre", "task": "add alert"}]},
  "mitigation is proven effective before the postmortem is written; every postmortem yields owned actions",
  steps=45, state_inputs=["alert"])

g("vuln-remediation-lifecycle", "security", "lifecycle",
  "Ingest a vulnerability, prioritize it, reproduce it, patch it, prove the patch, and disclose behind a human gate.",
  [P("ingest", "analyst", ["analyze"], ["advisory"], ins=["feed"]),
   P("prioritize", None, None, ["priority", "exploitability"], ins=["advisory"],
     sub="security/vuln-prioritization"),
   P("reproduce", "worker", ["run_command", "edit_files"], ["repro_confirmed"], ins=["priority"]),
   P("patch", "executor", ["execute_step", "edit_files"], ["patch"], ins=["repro_confirmed"]),
   P("prove", "verifier", ["run_command"], ["exploit_blocked"], ins=["patch"], kind="verifier"),
   GATE("disclose-approval", "signed_off == true and exploit_blocked == true",
        ["exploit_blocked"]),
   P("disclose", "producer", ["generate"], ["advisory_published"], ins=["signed_off"])],
  [("ingest", "prioritize"), ("prioritize", "reproduce"), ("reproduce", "patch"),
   ("patch", "prove"), ("prove", "patch", "not exploit_blocked and attempts < 3"),
   ("prove", "disclose-approval", "exploit_blocked"),
   ("disclose-approval", "disclose")],
  [("the exploit is proven blocked before anything is disclosed", "output.exploit_blocked == true"),
   ("disclosure carries a human signature", "output.signed_off == true"),
   ("the advisory actually shipped", "output.advisory_published == true")],
  {"exploit_blocked": True, "signed_off": True, "advisory_published": True},
  "nothing is disclosed until the exploit is proven blocked and a human has signed off",
  steps=45, state_inputs=["feed"])

g("schema-migration-saga", "data-analytics", "saga",
  "Migrate a schema in four reversible steps; any failure compensates back to a consistent state.",
  [P("plan", "planner", ["decompose_goal"], ["migration_plan"], ins=["source_schema"]),
   P("shadow-write", "migrator", ["shadow_write", "execute_step"], ["shadow_active"], ins=["migration_plan"]),
   P("backfill", "migrator", ["backfill", "execute_step"], ["backfill_complete"], ins=["shadow_active"]),
   P("cutover", "migrator", ["execute_step"], ["cutover_done"], ins=["backfill_complete"]),
   P("verify", "verifier", ["run_command"], ["parity_verified"], ins=["cutover_done"], kind="verifier"),
   P("undo-cutover", "compensator", ["rollback"], ["cutover_undone"], ins=["cutover_done"]),
   P("undo-backfill", "compensator", ["rollback"], ["backfill_undone"], ins=["backfill_complete"]),
   P("undo-shadow", "compensator", ["rollback"], ["shadow_undone", "consistent"], ins=["shadow_active"])],
  [("plan", "shadow-write"), ("shadow-write", "backfill"), ("backfill", "cutover"),
   ("cutover", "verify"),
   ("verify", "undo-cutover", "not parity_verified", "compensate"),
   ("cutover", "undo-cutover", "cutover_failed", "compensate"),
   ("backfill", "undo-backfill", "backfill_failed", "compensate"),
   ("shadow-write", "undo-shadow", "shadow_failed", "compensate"),
   ("undo-cutover", "undo-backfill"), ("undo-backfill", "undo-shadow")],
  [("the migration either verified or fully unwound — never partial",
    "output.parity_verified == true or output.consistent == true")],
  {"parity_verified": True, "consistent": False},
  "every forward step has a compensator; the saga ends verified or fully unwound",
  steps=40, state_inputs=["source_schema"])

g("framework-migration", "software-engineering", "supervisor-hierarchy",
  "Port a codebase between frameworks in verifiable slices, each slice delegated to a refactor subgraph.",
  [P("inventory", "analyst", ["analyze"], ["slices", "risk_map"], ins=["repo"]),
   P("supervise", "supervisor", ["delegate", "decompose_goal"], ["slice_queue"], ins=["slices"]),
   P("port-slice", None, None, ["slice_ported"], ins=["slice_queue"],
     sub="software-engineering/legacy-refactor"),
   P("integrate", "qa-lead", ["run_suite"], ["suite_green"], ins=["slice_ported"], kind="verifier"),
   P("sign-off", "tech-lead", ["read_diff"], ["migration_complete"], ins=["suite_green"], join="all")],
  [("inventory", "supervise"), ("supervise", "port-slice"), ("port-slice", "integrate"),
   ("integrate", "supervise", "not suite_green and attempts < 3"),
   ("integrate", "sign-off", "suite_green")],
  [("the full suite is green on the target stack", "output.suite_green == true"),
   ("every inventoried slice was ported", "output.slices_remaining == 0")],
  {"suite_green": True, "slices_remaining": 0},
  "build and full test suite green on the target stack with no slice left behind",
  steps=60, state_inputs=["repo"])

# ---- Tier B: human-gated, regulated ----------------------------------------

g("clinical-protocol-lifecycle", "healthcare-science", "human-gate",
  "Draft a study protocol, critique it against guidance, and register it only after investigator sign-off.",
  [P("draft", "producer", ["generate"], ["protocol"], ins=["study_goal"]),
   P("critique", "critic", ["critique"], ["deviations"], ins=["protocol"]),
   P("revise", "producer", ["generate"], ["protocol_final"], ins=["deviations"]),
   GATE("investigator-signoff", "signed_off == true and len(deviations) == 0", ["protocol_final"]),
   P("register", "controller", ["analyze", "file_record"], ["registered", "registry_id"], ins=["signed_off"])],
  [("draft", "critique"), ("critique", "revise", "len(deviations) > 0"),
   ("revise", "critique", "attempts < 3"),
   ("critique", "investigator-signoff", "len(deviations) == 0"),
   ("investigator-signoff", "register")],
  [("no unresolved guidance deviations at registration", "len(output.deviations) == 0"),
   ("a named investigator signed the protocol", "output.signed_off == true"),
   ("registration returned an id", "output.registry_id is not None")],
  {"deviations": [], "signed_off": True, "registry_id": "NCT00000001"},
  "a protocol registers only with zero open deviations and a named investigator signature",
  steps=35, state_inputs=["study_goal"],
  seed={"deviations": []})

g("contract-lifecycle", "legal-compliance", "human-gate",
  "Intake a contract, redline it, gate on residual risk, and execute only with counsel approval.",
  [P("intake", "analyst", ["analyze"], ["clauses"], ins=["contract"]),
   P("redline", None, None, ["redlines"], ins=["clauses"], sub="legal-compliance/contract-redline-pipeline"),
   P("risk-assess", "counsel", ["critique", "analyze"], ["residual_risk"], ins=["redlines"]),
   GATE("counsel-approval", "signed_off == true and residual_risk <= medium", ["residual_risk"]),
   P("execute", "executor", ["execute_step"], ["executed"], ins=["signed_off"])],
  [("intake", "redline"), ("redline", "risk-assess"),
   ("risk-assess", "redline", "residual_risk > medium and attempts < 2"),
   ("risk-assess", "counsel-approval", "residual_risk <= medium"),
   ("counsel-approval", "execute")],
  [("residual risk is at or below the accepted threshold", "output.residual_risk_level in ['low','medium']"),
   ("counsel signed before execution", "output.signed_off == true"),
   ("the contract was executed", "output.executed == true")],
  {"residual_risk_level": "low", "signed_off": True, "executed": True},
  "a contract executes only at or below medium residual risk with counsel signature",
  steps=35, state_inputs=["contract"],
  seed={"residual_risk": "low", "redlines": [{"clause": 7}]})

g("regulatory-filing-lifecycle", "finance", "human-gate",
  "Collect figures, reconcile them to source, gate on controller sign-off, then file and retain evidence.",
  [P("collect", "mapper", ["map_shard"], ["figures"], ins=["period"]),
   P("reconcile", "controller", ["analyze"], ["variance", "reconciled"], ins=["figures"]),
   GATE("controller-signoff", "signed_off == true and reconciled == true", ["reconciled"]),
   P("file", "controller", ["analyze", "file_record"], ["filed", "confirmation_id"], ins=["signed_off"]),
   P("retain", "producer", ["generate"], ["evidence_pack"], ins=["confirmation_id"])],
  [("collect", "reconcile"), ("reconcile", "collect", "not reconciled and attempts < 3"),
   ("reconcile", "controller-signoff", "reconciled"),
   ("controller-signoff", "file"), ("file", "retain")],
  [("figures tie to source before filing", "output.reconciled == true"),
   ("a controller signed the filing", "output.signed_off == true"),
   ("the filing is evidenced end to end", "output.filed == true and output.evidence_pack is not None")],
  {"reconciled": True, "signed_off": True, "filed": True, "evidence_pack": "s3://evidence/q3"},
  "nothing files until figures reconcile to source and a controller signs",
  steps=35, state_inputs=["period"])

g("gdpr-data-audit", "legal-compliance", "lifecycle",
  "Map personal data across systems, classify lawful basis, find gaps, and produce a remediation plan.",
  [P("discover", None, None, ["data_map"], ins=["systems"],
     sub="data-analytics/data-quality-audit"),
   P("classify", "analyst", ["analyze"], ["lawful_basis"], ins=["data_map"]),
   P("gap-scan", "critic", ["critique"], ["gaps"], ins=["lawful_basis"]),
   P("remediate", "planner", ["decompose_goal"], ["remediation_plan"], ins=["gaps"]),
   P("attest", "counsel", ["critique"], ["attested"], ins=["remediation_plan"], kind="verifier")],
  [("discover", "classify"), ("classify", "gap-scan"), ("gap-scan", "remediate"),
   ("remediate", "attest")],
  [("every mapped store has a stated lawful basis", "output.unclassified_stores == 0"),
   ("each gap carries an owner and a date", "all(gp.owner and gp.due for gp in output.gaps)")],
  {"unclassified_stores": 0, "gaps": [{"owner": "dpo", "due": "2026-09-01"}], "attested": True},
  "every store carries a lawful basis; every gap carries an owner and a due date",
  steps=30, state_inputs=["systems"])

g("trial-eligibility-screener", "healthcare-science", "escalation-ladder",
  "Screen patients against trial criteria cheapest-first, escalating ambiguous cases to a clinician.",
  [P("prefilter", "screener", ["screen"], ["obvious_excludes"], ins=["patient_records"]),
   P("criteria-match", "analyst", ["analyze"], ["matched", "ambiguous"], ins=["obvious_excludes"]),
   P("deep-review", "escalator", ["escalate", "classify_complexity"], ["escalated_cases"], ins=["ambiguous"]),
   GATE("clinician-review", "signed_off == true", ["escalated_cases"]),
   P("enrol", "executor", ["execute_step"], ["enrolled", "unreviewed_ambiguous"], ins=["matched"], join="any")],
  [("prefilter", "criteria-match"),
   ("criteria-match", "enrol", "len(ambiguous) == 0"),
   ("criteria-match", "deep-review", "len(ambiguous) > 0"),
   ("deep-review", "clinician-review"), ("clinician-review", "enrol")],
  [("no ambiguous case is enrolled without clinician review", "output.unreviewed_ambiguous == 0")],
  {"enrolled": 12, "unreviewed_ambiguous": 0},
  "an ambiguous eligibility decision never enrols without a clinician signature",
  steps=30, state_inputs=["patient_records"],
  seed={"ambiguous": [], "matched": [{"p": 1}]})

g("compliance-evidence-collector", "security", "lifecycle",
  "Walk a control framework, collect evidence per control, and flag controls with no live evidence.",
  [P("enumerate", "planner", ["decompose_goal"], ["controls"], ins=["framework"]),
   P("collect", None, None, ["evidence"], ins=["controls"],
     sub="devops-sre/runbook-executor"),
   P("assess", "reducer", ["reduce_merge"], ["coverage", "uncovered"], ins=["evidence"]),
   P("report", "producer", ["generate"], ["evidence_report"], ins=["coverage"], kind="verifier")],
  [("enumerate", "collect"), ("collect", "assess"),
   ("assess", "collect", "len(uncovered) > 0 and attempts < 2"),
   ("assess", "report")],
  [("every control is either evidenced or explicitly listed as uncovered",
    "output.controls_total == output.controls_evidenced + len(output.uncovered)")],
  {"controls_total": 40, "controls_evidenced": 38, "uncovered": [{"id": "AC-7"}, {"id": "AU-3"}]},
  "no control is silently unevidenced; the uncovered list is explicit",
  steps=30, state_inputs=["framework"],
  seed={"uncovered": [{"id": "AC-7"}, {"id": "AU-3"}]})

# ---- Tier C: orphan-domain fills -------------------------------------------

g("hiring-lifecycle", "hr-people", "human-gate",
  "Draft a role, screen a pipeline, run a structured interview loop, and gate the offer on a panel decision.",
  [P("define-role", None, None, ["jd"], ins=["role_brief"], sub="hr-people/jd-drafting-critic"),
   P("screen", "recruiter", ["screen"], ["shortlist"], ins=["jd"]),
   P("interview", "analyst", ["analyze"], ["scorecards"], ins=["shortlist"]),
   GATE("panel-decision", "signed_off == true and len(scorecards) >= 3", ["scorecards"]),
   P("offer", "executor", ["execute_step"], ["offer_sent", "structured"], ins=["signed_off"])],
  [("define-role", "screen"), ("screen", "interview"),
   ("interview", "screen", "len(shortlist) == 0 and attempts < 2"),
   ("interview", "panel-decision", "len(scorecards) >= 3"),
   ("panel-decision", "offer")],
  [("no offer without a quorum of structured scorecards", "output.scorecard_count >= 3"),
   ("a panel, not a model, made the call", "output.signed_off == true")],
  {"scorecard_count": 4, "signed_off": True, "offer_sent": True, "structured": True},
  "an offer requires at least three structured scorecards and a panel signature",
  steps=35, state_inputs=["role_brief"],
  seed={"scorecards": [{"i": 1}, {"i": 2}, {"i": 3}], "shortlist": [{"c": "a"}]})

g("onboarding-plan-builder", "hr-people", "lifecycle",
  "Build a role-specific 30/60/90 plan from the JD, team context and access requirements, then verify coverage.",
  [P("gather", "analyst", ["analyze"], ["role_context"], ins=["role", "team"]),
   P("draft-plan", "producer", ["generate"], ["plan_30_60_90"], ins=["role_context"]),
   P("access-map", "mapper", ["map_shard"], ["access_requests"], ins=["role_context"]),
   P("review", "critic", ["critique"], ["milestones_covered"], ins=["plan_30_60_90", "access_requests"],
     kind="verifier", join="all")],
  [("gather", "draft-plan"), ("gather", "access-map"),
   ("draft-plan", "review"), ("access-map", "review"),
   ("review", "draft-plan", "not milestones_covered and attempts < 2")],
  [("all three checkpoints have a measurable milestone", "output.milestones_covered == true"),
   ("day-one access is requested before the start date", "output.access_requested == true")],
  {"milestones_covered": True, "access_requested": True},
  "every checkpoint carries a measurable milestone and day-one access is pre-requested",
  steps=25, state_inputs=["role", "team"])

g("performance-cycle-summarizer", "hr-people", "lifecycle",
  "Aggregate self, peer and manager input into a calibrated summary with evidence for every claim.",
  [P("gather", "mapper", ["map_shard"], ["inputs"], ins=["cycle"]),
   P("synthesize", "reducer", ["reduce_merge"], ["draft_summary"], ins=["inputs"]),
   P("bias-check", "critic", ["critique"], ["bias_flags"], ins=["draft_summary"]),
   P("calibrate", "judge", ["adjudicate"], ["calibrated_summary"], ins=["bias_flags"], kind="verifier")],
  [("gather", "synthesize"), ("synthesize", "bias-check"),
   ("bias-check", "synthesize", "len(bias_flags) > 0 and attempts < 2"),
   ("bias-check", "calibrate", "len(bias_flags) == 0")],
  [("every claim cites a source input", "output.uncited_claims == 0"),
   ("no unresolved bias flag survives calibration", "len(output.bias_flags) == 0")],
  {"uncited_claims": 0, "bias_flags": []},
  "every statement cites an input and no bias flag survives calibration",
  steps=25, state_inputs=["cycle"],
  seed={"bias_flags": []})

g("procurement-lifecycle", "business-ops", "human-gate",
  "Run an RFP, score vendors, negotiate terms, and gate the award on budget-holder approval.",
  [P("rfp", None, None, ["rfp_responses"], ins=["requirement"], sub="business-ops/rfp-response-assembler"),
   P("score", "evaluator", ["evaluate"], ["vendor_scores"], ins=["rfp_responses"]),
   P("negotiate", "buyer", ["negotiate", "analyze"], ["terms", "savings"], ins=["vendor_scores"]),
   GATE("budget-approval", "signed_off == true", ["terms"]),
   P("award", "executor", ["execute_step"], ["awarded", "scored_vendors"], ins=["signed_off"])],
  [("rfp", "score"), ("score", "negotiate"),
   ("negotiate", "score", "savings < target_savings and attempts < 2"),
   ("negotiate", "budget-approval"), ("budget-approval", "award")],
  [("at least three vendors were scored on the same rubric", "output.scored_vendors >= 3"),
   ("the budget holder approved the award", "output.signed_off == true")],
  {"scored_vendors": 3, "signed_off": True, "awarded": True},
  "no award without three rubric-scored vendors and a budget-holder signature",
  steps=35, state_inputs=["requirement"])

g("vendor-comparison-matrix", "business-ops", "lifecycle",
  "Build a like-for-like vendor matrix where every cell cites the source document it came from.",
  [P("collect", None, None, ["vendor_docs"], ins=["vendors"],
     sub="research-knowledge/competitive-intelligence"),
   P("normalize", "analyst", ["analyze"], ["criteria_grid"], ins=["vendor_docs"]),
   P("fill", "reducer", ["reduce_merge"], ["matrix"], ins=["criteria_grid"]),
   P("cite-check", "critic", ["critique"], ["uncited_cells"], ins=["matrix"], kind="verifier")],
  [("collect", "normalize"), ("normalize", "fill"), ("fill", "cite-check"),
   ("cite-check", "fill", "uncited_cells > 0 and attempts < 2")],
  [("every filled cell cites a source document", "output.uncited_cells == 0"),
   ("all vendors are scored on identical criteria", "output.criteria_consistent == true")],
  {"uncited_cells": 0, "criteria_consistent": True},
  "every matrix cell cites its source and all vendors share one criteria set",
  steps=25, state_inputs=["vendors"])

g("invoice-reconciliation", "business-ops", "escalation-ladder",
  "Match invoices to POs and receipts cheapest-first, escalating only genuine exceptions to a human.",
  [P("auto-match", None, None, ["matched", "exceptions"], ins=["invoices"],
     sub="finance/expense-audit-swarm"),
   P("fuzzy-match", "escalator", ["escalate", "classify_complexity"], ["still_open"], ins=["exceptions"]),
   GATE("ap-review", "signed_off == true", ["still_open"]),
   P("post", "controller", ["analyze"], ["posted", "unreviewed_exceptions"], ins=["matched"], join="any")],
  [("auto-match", "post", "len(exceptions) == 0"),
   ("auto-match", "fuzzy-match", "len(exceptions) > 0"),
   ("fuzzy-match", "post", "len(still_open) == 0"),
   ("fuzzy-match", "ap-review", "len(still_open) > 0"),
   ("ap-review", "post")],
  [("no exception posts without human review", "output.unreviewed_exceptions == 0"),
   ("three-way match holds for everything posted", "output.three_way_matched == true")],
  {"posted": 128, "unreviewed_exceptions": 0, "three_way_matched": True},
  "an unmatched invoice never posts without an AP signature",
  steps=30, state_inputs=["invoices"],
  seed={"exceptions": [], "matched": [{"inv": 1}]})

g("book-editing-pipeline", "creative-production", "lifecycle",
  "Take a manuscript through developmental, line and copy edit passes with author sign-off before typesetting.",
  [P("assess", "critic", ["critique"], ["dev_notes"], ins=["manuscript"]),
   P("dev-edit", "producer", ["generate"], ["dev_draft"], ins=["dev_notes"]),
   P("line-edit", "producer", ["generate"], ["line_draft"], ins=["dev_draft"]),
   P("copy-edit", "critic", ["critique"], ["copy_clean", "style_violations"], ins=["line_draft"]),
   GATE("author-signoff", "signed_off == true and len(style_violations) == 0", ["copy_clean"]),
   P("typeset", "executor", ["execute_step"], ["typeset"], ins=["signed_off"])],
  [("assess", "dev-edit"), ("dev-edit", "line-edit"), ("line-edit", "copy-edit"),
   ("copy-edit", "line-edit", "len(style_violations) > 0 and attempts < 2"),
   ("copy-edit", "author-signoff", "len(style_violations) == 0"),
   ("author-signoff", "typeset")],
  [("no style guide violations survive to typesetting", "len(output.style_violations) == 0"),
   ("the author approved the final text", "output.signed_off == true")],
  {"style_violations": [], "signed_off": True, "typeset": True},
  "nothing typesets with open style violations or without author sign-off",
  steps=35, state_inputs=["manuscript"],
  seed={"style_violations": []})

g("podcast-production-pipeline", "creative-production", "lifecycle",
  "Turn a raw recording into a published episode: transcript, edit plan, show notes, rights check, publish.",
  [P("transcribe", "mapper", ["map_shard"], ["transcript"], ins=["recording"]),
   P("edit-plan", "producer", ["generate"], ["cut_list"], ins=["transcript"]),
   P("show-notes", "producer", ["generate"], ["show_notes", "timestamps"], ins=["cut_list"]),
   P("rights-check", "counsel", ["critique"], ["clearances", "rights_clear"], ins=["cut_list"]),
   P("publish", "executor", ["execute_step"], ["published"], ins=["show_notes", "rights_clear"],
     join="all")],
  [("transcribe", "edit-plan"), ("edit-plan", "show-notes"), ("edit-plan", "rights-check"),
   ("show-notes", "publish"), ("rights-check", "publish", "rights_clear")],
  [("every music or clip cue is cleared before publish", "output.rights_clear == true"),
   ("show notes timestamps line up with the cut", "output.timestamps_valid == true")],
  {"rights_clear": True, "timestamps_valid": True, "published": True},
  "no episode publishes with an uncleared cue or drifting timestamps",
  steps=30, state_inputs=["recording"],
  seed={"rights_clear": True})

g("screenplay-coverage", "creative-production", "lifecycle",
  "Produce studio-standard coverage: synopsis, structural analysis, comparables, and a defended recommendation.",
  [P("read", "analyst", ["analyze"], ["synopsis", "beats"], ins=["screenplay"]),
   P("structure", "critic", ["critique"], ["structure_notes"], ins=["beats"]),
   P("comparables", None, None, ["comps"], ins=["synopsis"],
     sub="research-knowledge/competitive-intelligence"),
   P("recommend", "judge", ["adjudicate"], ["recommendation", "rationale"],
     ins=["structure_notes", "comps"], kind="verifier", join="all")],
  [("read", "structure"), ("read", "comparables"),
   ("structure", "recommend"), ("comparables", "recommend")],
  [("the recommendation is one of the studio-standard verdicts",
    "output.recommendation in ['pass','consider','recommend']"),
   ("the verdict is defended against named comparables", "len(output.comps) >= 2")],
  {"recommendation": "consider", "comps": [{"title": "A"}, {"title": "B"}]},
  "coverage lands one of three verdicts, defended against at least two named comparables",
  steps=25, state_inputs=["screenplay"])

g("supplier-risk-monitor", "logistics-retail", "lifecycle",
  "Score supplier concentration, financial and geographic risk, then plan mitigation for anything above appetite.",
  [P("ingest", None, None, ["supplier_signals"], ins=["supplier_list"],
     sub="research-knowledge/competitive-intelligence"),
   P("score", "analyst", ["analyze"], ["risk_scores"], ins=["supplier_signals"]),
   P("concentrate", "analyst", ["analyze"], ["concentration"], ins=["risk_scores"]),
   P("mitigate", "planner", ["decompose_goal"], ["mitigations"], ins=["concentration"], kind="verifier")],
  [("ingest", "score"), ("score", "concentrate"), ("concentrate", "mitigate")],
  [("every supplier above appetite has a named mitigation",
    "output.above_appetite == output.mitigations_planned"),
   ("single-source dependencies are called out explicitly", "output.single_source_flagged == true")],
  {"above_appetite": 4, "mitigations_planned": 4, "single_source_flagged": True},
  "every supplier above risk appetite carries a named mitigation owner",
  steps=25, state_inputs=["supplier_list"])

g("product-listing-pipeline", "logistics-retail", "lifecycle",
  "Generate marketplace listings from spec sheets, checking claims against source and policy before publish.",
  [P("extract", "mapper", ["map_shard"], ["attributes"], ins=["spec_sheets"]),
   P("write", "producer", ["generate"], ["listing_copy"], ins=["attributes"]),
   P("claim-check", None, None, ["unsupported_claims"], ins=["listing_copy", "attributes"],
     sub="research-knowledge/fact-check-pipeline", join="all"),
   P("policy-check", "critic", ["critique"], ["policy_violations"], ins=["listing_copy"]),
   P("publish", "executor", ["execute_step"], ["listings_published"],
     ins=["unsupported_claims", "policy_violations"], join="all")],
  [("extract", "write"), ("write", "claim-check"), ("write", "policy-check"),
   ("claim-check", "write", "len(unsupported_claims) > 0 and attempts < 2"),
   ("claim-check", "publish", "len(unsupported_claims) == 0"),
   ("policy-check", "publish", "len(policy_violations) == 0")],
  [("no listing claim lacks a spec-sheet source", "len(output.unsupported_claims) == 0"),
   ("no marketplace policy violation ships", "len(output.policy_violations) == 0")],
  {"unsupported_claims": [], "policy_violations": [], "listings_published": 40},
  "every published claim traces to the spec sheet and clears marketplace policy",
  steps=30, state_inputs=["spec_sheets"],
  seed={"policy_violations": [], "unsupported_claims": []})


# --------------------------------------------------------------------- emitter


def build(spec: dict) -> dict:
    edges = []
    for e in spec["edges"]:
        d = {"from": e[0], "to": e[1]}
        if len(e) > 2 and e[2]:
            d["when"] = e[2]
        if len(e) > 3:
            d["kind"] = e[3]
        edges.append(d)
    doc = {
        "apiVersion": "agr/v1.1",
        "name": spec["name"],
        "description": spec["summary"],
        "category": spec["domain"],
        "nodes": spec["phases"],
        "edges": edges,
        "termination": {"max_steps": spec["steps"], "contract": spec["contract"]},
        "verification": [{"describe": d, "assert": a} for d, a in spec["checks"]],
    }
    if spec["state_inputs"]:
        doc["state"] = {"inputs": spec["state_inputs"]}
    return doc


_SAMPLE = {"list": [], "int": 0, "bool": True, "str": "ok"}


def _stub(key: str):
    """A plausible fixture value for a declared output key."""
    if key.startswith("len_") or key.endswith(("_count", "_total")):
        return 1
    if key.endswith(("s", "list", "queue", "notes", "map", "grid")):
        return []
    if key.startswith(("is_", "has_")) or key.endswith(
        ("ed", "_clear", "_green", "_covered", "_verified", "_consistent", "_valid", "_active")
    ):
        return True
    return f"{key}-value"


def _child_fixtures(phase_id: str, ref: str) -> dict:
    """Borrow the child graph's own golden case, prefixed with the phase id.

    A composite inherits its children's contracts (v1.2 evaluates a child's
    asserts against that phase's terminal frame), so it must also inherit
    fixtures that satisfy them. The child's first golden case already does, by
    construction — reusing it is both less code and more honest than
    re-inventing values that happen to pass.
    """
    child_name = ref.split("/")[-1]
    cases = ROOT / "evals" / child_name / "cases.yaml"
    if not cases.exists():
        return {}
    first = yaml.safe_load(cases.read_text())["cases"][0]["node_outputs"]
    return {f"{phase_id}.{nid}": out for nid, out in first.items()}


def cases_for(spec: dict, doc: dict) -> dict:
    """One happy-path golden case whose fixtures satisfy the declared contract.

    Fixtures are built against the *expanded* graph, because that is what runs:
    a phase declared as `kind: subgraph` contributes its child's node ids, and
    those children need fixtures too.

    Precedence per output key: explicit `seed` > the value the graph's `final`
    object asserts > a type-shaped stub. Anchoring intermediate fixtures to
    `final` keeps the run self-consistent — a graph cannot assert
    `output.exploit_blocked == true` while its `prove` phase emitted something else.
    """
    pins = {**spec["final"], **spec["seed"]}
    outs: dict[str, dict] = {}
    # Inherit each subgraph phase's fixtures from the child's own golden case.
    for n in doc["nodes"]:
        if n.get("kind") == "subgraph":
            outs.update(_child_fixtures(n["id"], n["ref"]))
    doc = expand(doc, ROOT)
    for n in doc["nodes"]:
        vals = {k: (pins[k] if k in pins else _stub(k)) for k in n.get("outputs") or []}
        if n.get("kind") == "human":
            vals["signed_off"] = True  # the happy path is an approving human
        # A borrowed child fixture already satisfies the child's contract; only
        # add the phase's declared outputs on top of it.
        outs[n["id"]] = {**vals, **outs.get(n["id"], {})} if "." in n["id"] else vals
    # Every terminal carries the result object: which one the happy path reaches
    # depends on the branch taken, and a saga's compensators are terminals too.
    for t in _terminals(doc):
        outs.setdefault(t, {})["output"] = spec["final"]
    return {"cases": [{"id": "happy-path", "node_outputs": outs}]}


def _terminals(doc):
    order = {n["id"]: i for i, n in enumerate(doc["nodes"])}
    fwd = {e["from"] for e in doc["edges"]
           if e.get("kind", "flow") == "flow" and order.get(e["to"], 0) > order.get(e["from"], -1)}
    return [n["id"] for n in doc["nodes"] if n["id"] not in fwd]


def main() -> None:
    written = 0
    for spec in G:
        doc = build(spec)
        out = ROOT / "graphs" / spec["domain"] / spec["name"] / "graph.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
        ev = ROOT / "evals" / spec["name"] / "cases.yaml"
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text(yaml.safe_dump(cases_for(spec, doc), sort_keys=False, width=100))
        written += 1
    total = len(list((ROOT / "graphs").glob("*/*/graph.yaml")))
    print(f"wrote {written} v1.1 composites; registry now {total} graphs")


if __name__ == "__main__":
    main()
