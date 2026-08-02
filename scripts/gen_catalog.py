"""Single source of truth for the use-case catalog. Regenerates usecases/catalog.yaml."""
from pathlib import Path

import yaml

# (name, domain, pattern, summary, verification)
E = [
 # software-engineering
 ("code-review-pipeline","software-engineering","pipeline","Staged PR review with risk triage and parallel security plus style passes.","verdict in approve or request_changes; findings carry file and line"),
 ("bug-triage-and-fix","software-engineering","planner-executor-verifier","Reproduce a bug, plan a fix, apply it in isolation, verify.","repro test fails before patch and passes after"),
 ("test-suite-generation","software-engineering","generator-critic","Generate tests, critic rejects trivial or tautological assertions.","coverage delta positive; mutation score above baseline"),
 ("legacy-refactor","software-engineering","pipeline","Refactor a module behind characterization tests.","behavior snapshot tests unchanged before and after"),
 ("framework-migration","software-engineering","planner-executor-verifier","Port a codebase between frameworks in verifiable slices.","build and full test suite green on target stack"),
 ("dependency-upgrade","software-engineering","pipeline","Upgrade pinned deps, scan changelogs for breakage, run suite.","lockfile updated; tests pass; no new deprecation warnings"),
 ("api-design-review","software-engineering","debate","Two reviewers argue REST versus RPC tradeoffs, judge synthesizes.","spec passes lint; breaking changes enumerated"),
 ("performance-optimization","software-engineering","loop","Profile, patch hotspot, re-benchmark until budget met.","benchmark under target with no test regressions"),
 ("release-notes-generation","software-engineering","map-reduce","Summarize merged PRs per area, reduce into release notes.","every note links a merged PR; no orphan claims"),
 ("docs-code-sync-audit","software-engineering","parallel-swarm","Workers execute every doc example against the current API.","all documented examples run exit zero"),
 # devops-sre
 ("incident-triage-router","devops-sre","router","Classify severity and route incidents to the owning team.","routing matches on-call ownership map"),
 ("runbook-executor","devops-sre","planner-executor-verifier","Execute a runbook step-wise with post-condition checks.","each step post-condition command exits zero"),
 ("alert-noise-reduction","devops-sre","map-reduce","Cluster alerts, dedupe storms, emit one incident per cause.","dedupe ratio measured; no missed paging alert"),
 ("cloud-cost-optimizer","devops-sre","pipeline","Scan usage, propose rightsizing, verify against SLO headroom.","projected savings computed from real billing export"),
 ("deploy-canary-verifier","devops-sre","loop","Progressively shift traffic while checking error budgets.","rollback fires when error rate exceeds threshold"),
 ("postmortem-writer","devops-sre","pipeline","Assemble timeline from logs and chat, draft blameless postmortem.","every timeline event cites a log or message id"),
 ("capacity-forecaster","devops-sre","generator-critic","Forecast load, critic stress-tests assumptions against history.","backtest error within stated confidence band"),
 # data-analytics
 ("sql-generation-verified","data-analytics","generator-critic","Generate SQL, critic checks schema validity and row sanity.","query executes; result passes row-count sanity assertions"),
 ("etl-pipeline-builder","data-analytics","planner-executor-verifier","Design and build an ETL job from source to warehouse.","end-to-end run loads expected row counts"),
 ("data-quality-audit","data-analytics","parallel-swarm","Workers profile each table for nulls, drift, and duplicates.","violations emitted as machine-readable rules with counts"),
 ("dashboard-builder","data-analytics","pipeline","From metric spec to working dashboard with tested queries.","every panel query executes under latency budget"),
 ("schema-migration-planner","data-analytics","planner-executor-verifier","Plan backward-compatible schema changes with shadow reads.","shadow-read diff empty before cutover"),
 ("anomaly-investigation","data-analytics","router","Route metric anomalies to seasonal, data-bug, or real-change analysts.","classification agrees with holdout labels"),
 ("ab-test-analysis","data-analytics","debate","Two analysts argue significance and pitfalls, judge writes readout.","stats recomputed from raw data reproduce claimed effect"),
 ("data-catalog-enrichment","data-analytics","map-reduce","Describe every table and column, reduce into a searchable catalog.","descriptions exist for all tables; lineage links resolve"),
 # research-knowledge
 ("literature-review-swarm","research-knowledge","parallel-swarm","Parallel readers summarize papers, merger builds themed review.","every claim cites a specific paper and section"),
 ("systematic-meta-analysis","research-knowledge","pipeline","PRISMA-style screen, extract, pool effect sizes.","inclusion log complete; effect sizes recomputable"),
 ("competitive-intelligence","research-knowledge","map-reduce","Scan competitor releases and filings, reduce to a delta brief.","every finding links a dated public source"),
 ("fact-check-pipeline","research-knowledge","pipeline","Decompose claims, verify each against sources, grade verdicts.","each verdict carries source URL and quote span"),
 ("patent-landscape","research-knowledge","map-reduce","Cluster patents by claim family, summarize white space.","cluster assignments reproducible; ids valid"),
 ("survey-design-critic","research-knowledge","generator-critic","Draft survey, critic hunts leading and double-barreled items.","zero flagged items remain; branching logic validated"),
 ("grant-proposal-pipeline","research-knowledge","pipeline","Aims, methods, budget drafted then compliance-checked.","funder checklist items all satisfied"),
 ("citation-integrity-audit","research-knowledge","parallel-swarm","Workers verify each citation exists and supports its claim.","every citation resolves; mismatches listed"),
 # content-marketing
 ("blog-production-pipeline","content-marketing","pipeline","Brief to outline to draft to edit to publish-ready post.","style guide lint passes; plagiarism scan clean"),
 ("seo-optimization-loop","content-marketing","loop","Rewrite for target queries, re-score, iterate to threshold.","seo score above threshold without keyword stuffing flags"),
 ("ad-variant-tournament","content-marketing","generator-critic","Generate ad variants, critic ranks against brand and claim rules.","surviving variants pass legal claim checklist"),
 ("brand-consistency-audit","content-marketing","parallel-swarm","Workers audit assets against voice and visual guidelines.","violations reported per asset with rule ids"),
 ("localization-pipeline","content-marketing","map-reduce","Translate per locale, reduce into a consistency report.","back-translation similarity above threshold; glossary respected"),
 ("social-campaign-planner","content-marketing","planner-executor-verifier","Plan a campaign calendar, draft posts, verify constraints.","calendar has no channel conflicts; lengths within limits"),
 ("newsletter-assembler","content-marketing","map-reduce","Summarize the period's items, reduce into sections.","every item links its source; dead links zero"),
 ("video-script-writer","content-marketing","generator-critic","Script drafts critiqued for hook, pacing, and claim accuracy.","runtime estimate within brief; claims sourced"),
 # business-ops
 ("rfp-response-assembler","business-ops","map-reduce","Answer each RFP requirement from a knowledge base, assemble.","every requirement answered or flagged; page limit met"),
 ("meeting-to-actions","business-ops","pipeline","Transcript to decisions, owners, deadlines, and follow-ups.","each action has owner and date; quotes traceable"),
 ("vendor-comparison-matrix","business-ops","parallel-swarm","Workers score vendors per criterion from evidence.","every score cites vendor documentation"),
 ("policy-compliance-check","business-ops","pipeline","Check internal docs and processes against a policy set.","findings map to specific policy clause ids"),
 ("okr-drafting-debate","business-ops","debate","Ambition versus feasibility advocates converge on OKRs.","each KR is measurable with a data source named"),
 ("invoice-reconciliation","business-ops","router","Match invoices to POs, route exceptions by mismatch type.","matched set balances; exceptions carry mismatch reason"),
 ("process-documentation-miner","business-ops","map-reduce","Mine tickets and chats to document the de facto process.","steps corroborated by at least two sources"),
 # finance
 ("earnings-call-digest","finance","pipeline","Transcript to guidance changes, surprises, and QA highlights.","every figure matches transcript; no invented numbers"),
 ("budget-variance-analysis","finance","map-reduce","Explain variance per cost center, reduce to an exec brief.","variances sum to total; drivers cite ledger lines"),
 ("fraud-pattern-triage","finance","router","Route flagged transactions to rule, anomaly, or manual review.","routing precision measured against labeled history"),
 ("kyc-document-processing","finance","pipeline","Extract, cross-check, and flag gaps in KYC documents.","extracted fields validate against document images"),
 ("regulatory-filing-check","finance","parallel-swarm","Workers check filing sections against requirement checklists.","every checklist item pass or fail with location"),
 ("portfolio-report-generation","finance","pipeline","Assemble informational holdings and performance reporting.","figures reconcile to custodian data; no advice emitted"),
 ("expense-audit-swarm","finance","parallel-swarm","Workers audit expense lines against policy in parallel.","violations carry line id and policy rule"),
 # legal-compliance
 ("contract-redline-pipeline","legal-compliance","pipeline","Compare against playbook, propose redlines with rationale.","every redline cites a playbook position"),
 ("license-compliance-scan","legal-compliance","map-reduce","Scan dependency licenses, reduce to obligations report.","SPDX ids resolved; copyleft conflicts flagged"),
 ("gdpr-data-audit","legal-compliance","parallel-swarm","Workers map personal data flows per system.","every flow lists lawful basis or a gap"),
 ("ediscovery-triage","legal-compliance","router","Route documents by privilege, relevance, and confidentiality.","recall on seeded relevant set above threshold"),
 ("case-law-research","legal-compliance","pipeline","Find, shepardize, and brief controlling authority.","every citation verified as good law with source"),
 ("tos-diff-monitor","legal-compliance","pipeline","Diff terms-of-service versions, classify materiality.","each material change quotes old and new text"),
 ("ip-portfolio-review","legal-compliance","map-reduce","Review marks and patents for renewals and conflicts.","deadlines extracted match registry records"),
 # healthcare-science
 ("clinical-literature-triage","healthcare-science","router","Route new papers by study type and evidence level.","labels match a validated sample set"),
 ("protocol-drafting-critic","healthcare-science","generator-critic","Draft study protocols, critic checks power and ethics gaps.","checklist conformance complete; power calc reproducible"),
 ("medical-coding-audit","healthcare-science","parallel-swarm","Workers verify diagnosis and procedure codes against notes.","code assignments justified by note spans"),
 ("bioinformatics-pipeline-builder","healthcare-science","planner-executor-verifier","Assemble genomics workflow with validated steps.","pipeline reproduces reference results on test data"),
 ("adverse-event-scanner","healthcare-science","map-reduce","Scan reports for adverse-event signals, reduce to summary.","every signal cites report ids; counts reproducible"),
 ("lab-notebook-summarizer","healthcare-science","pipeline","Turn raw notebook entries into structured experiment records.","records validate against schema; entries linked"),
 ("trial-eligibility-screener","healthcare-science","pipeline","Screen criteria against records for informational matching.","each criterion pass or fail with evidence span"),
 # education
 ("curriculum-designer","education","planner-executor-verifier","Design course from outcomes to assessments with alignment.","every outcome mapped to lesson and assessment"),
 ("quiz-generation-verified","education","generator-critic","Generate items, critic solves them blind to verify keys.","critic answers match keys; distractors plausible"),
 ("essay-feedback-critic","education","generator-critic","Rubric-based feedback with evidence quotes from the essay.","every comment quotes essay text; rubric ids cited"),
 ("tutoring-router","education","router","Route learner questions by topic and difficulty to tutors.","routing matches topic taxonomy on holdout set"),
 ("learning-path-planner","education","planner-executor-verifier","Sequence modules against prerequisites and pace.","prerequisite DAG has no violations"),
 ("rubric-grading-swarm","education","parallel-swarm","Independent graders score, disagreements auto-escalate.","inter-rater agreement above threshold or escalated"),
 ("course-localization","education","map-reduce","Localize materials per language, reduce into a QA report.","terminology glossary respected; media links valid"),
 # customer-support-sales
 ("ticket-triage-swarm","customer-support-sales","router","Classify and route tickets with priority and sentiment.","routing accuracy measured on labeled backlog"),
 ("kb-article-generator","customer-support-sales","pipeline","Mine resolved tickets into draft knowledge-base articles.","steps reproduce resolution; duplicates deduped"),
 ("escalation-summarizer","customer-support-sales","pipeline","Compress long threads into handoff briefs with state.","brief covers all unresolved asks; quotes traceable"),
 ("churn-signal-analysis","customer-support-sales","map-reduce","Aggregate account signals, reduce to ranked churn risks.","every risk factor cites underlying events"),
 ("crm-enrichment-pipeline","customer-support-sales","pipeline","Fill CRM gaps from public sources with provenance.","each field carries source URL and timestamp"),
 ("sales-call-scorer","customer-support-sales","parallel-swarm","Workers score calls per methodology dimension.","scores cite transcript spans; calibration checked"),
 ("quote-configurator","customer-support-sales","pipeline","Assemble quotes against price book and discount policy.","totals recompute exactly; policy violations zero"),
 # security
 ("threat-intel-digest","security","map-reduce","Summarize feeds into an actionable daily brief.","every item links source advisory with CVE ids"),
 ("phishing-triage","security","router","Classify reported emails, route confirmed phish to response.","verdicts benchmarked against labeled corpus"),
 ("vuln-prioritization","security","pipeline","Rank findings by exploitability and blast radius.","ranking inputs cite scanner evidence and asset map"),
 ("soc-alert-investigation","security","planner-executor-verifier","Investigate an alert with hypothesis-driven queries.","conclusion supported by query results attached"),
 ("pentest-report-synthesis","security","pipeline","Merge tester notes into a findings report with severities.","every finding has repro steps and evidence"),
 ("supply-chain-audit","security","parallel-swarm","Workers audit dependencies for provenance and tampering.","attestations verified; unsigned artifacts listed"),
 ("compliance-evidence-collector","security","map-reduce","Gather control evidence per framework requirement.","every control maps to dated evidence artifacts"),
 # hr-people
 ("jd-drafting-critic","hr-people","generator-critic","Draft job descriptions, critic removes bias and inflation.","bias-term lint clean; requirements deduplicated"),
 ("interview-question-bank","hr-people","generator-critic","Generate role questions, critic checks legality and signal.","no prohibited-topic questions; rubric attached"),
 ("onboarding-plan-builder","hr-people","planner-executor-verifier","Build role-specific onboarding with checkpoint tasks.","every task has owner, system access verified"),
 ("engagement-survey-analysis","hr-people","map-reduce","Theme open-text responses, reduce with anonymity floor.","themes cite response counts; k-anonymity respected"),
 ("policy-qa-assistant","hr-people","pipeline","Answer policy questions with citations to the handbook.","every answer cites handbook section"),
 ("performance-cycle-summarizer","hr-people","pipeline","Aggregate peer feedback into balanced review drafts.","every statement traces to submitted feedback"),
 ("training-gap-analyzer","hr-people","map-reduce","Map skills against role matrix, reduce to training plan.","gaps reference assessment evidence"),
 # logistics-retail
 ("route-optimization-review","logistics-retail","generator-critic","Propose delivery routes, critic checks constraints.","routes satisfy time windows and capacity"),
 ("inventory-forecast-critic","logistics-retail","generator-critic","Forecast SKU demand, critic backtests against history.","backtest error below naive baseline"),
 ("supplier-risk-monitor","logistics-retail","map-reduce","Scan supplier news and filings, reduce to risk deltas.","every delta links a dated source"),
 ("product-listing-pipeline","logistics-retail","pipeline","Draft listings from specs with claim and image checks.","attributes match spec sheet; banned claims zero"),
 ("returns-triage","logistics-retail","router","Route returns by reason to refund, repair, or fraud review.","routing agrees with policy decision table"),
 ("demand-signal-digest","logistics-retail","map-reduce","Merge sales, weather, and events into demand notes.","signals quantified with source data ranges"),
 ("planogram-compliance-review","logistics-retail","parallel-swarm","Workers check shelf photos against planograms.","violations localized per fixture with confidence"),
 # creative-production
 ("screenplay-coverage","creative-production","pipeline","Read script, produce coverage with comps and verdict.","verdict rubric complete; quotes have page numbers"),
 ("podcast-production-pipeline","creative-production","pipeline","Outline, script, edit, and show notes with links.","chapters match audio markers; links resolve"),
 ("game-npc-dialogue","creative-production","generator-critic","Generate branching dialogue, critic checks lore and tone.","branches validate against dialogue schema; lore conflicts zero"),
 ("level-design-review","creative-production","debate","Difficulty versus flow advocates review a level design.","playtest checklist complete; blockers enumerated"),
 ("book-editing-pipeline","creative-production","pipeline","Developmental, line, and copy edits in ordered passes.","style sheet applied; continuity errors listed resolved"),
 ("ux-research-synthesis","creative-production","map-reduce","Code interview transcripts, reduce to themed insights.","every insight cites at least two participants"),
 ("image-asset-qa","creative-production","parallel-swarm","Workers check assets for spec, licensing, and artifacts.","every asset pass or fail with rule id"),
 ("music-metadata-tagging","creative-production","map-reduce","Tag tracks with genre, mood, and rights metadata.","tags validate against controlled vocabulary"),
]

def main() -> None:
    entries = [
        {"id": f"uc-{i:03d}", "name": n, "domain": d, "pattern": p, "summary": s, "verification": v}
        for i, (n, d, p, s, v) in enumerate(E, 1)
    ]
    out = Path(__file__).resolve().parents[1] / "usecases" / "catalog.yaml"
    out.write_text(yaml.safe_dump({"apiVersion": "agr/v1", "kind": "UseCaseCatalog", "entries": entries},
                                  sort_keys=False, width=120, allow_unicode=True))
    print(f"wrote {out} with {len(entries)} entries")

if __name__ == "__main__":
    main()
