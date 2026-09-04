# Milestones — what each spec version closed

The per-milestone record, moved out of the README in v1.8. Each entry names the
gap the version found and what it did about it; several of them are corrections
of an earlier version's diagnosis, which is why they are worth keeping whole.

The README keeps the current state and a pointer here.

- [x] **M0** — AGR v1 spec, validator + MAST lint, `agr` CLI, 52 validating graphs, audit-gated 112-entry catalog
- [x] **M1** — eval harness (`agr eval`): real graph interpreter (routers, joins, bounded loops,
      contract asserts) + pluggable runners. Mock-fixture profiles are marked `provisional`;
      set `AGR_LLM_BASE_URL`/`AGR_LLM_MODEL` and pass `--live` for model-quality numbers.
- [x] **M2** — `agr infuse` (ability injection; schema+lint+golden-case gated, lineage-logged)
      and `agr optimize` (v0 deterministic hill-climb: dedupe, sibling parallelization,
      measurement-driven `max_steps` tightening). AFlow-style MCTS search remains open.
- [x] **M3** — LangGraph adapter (`agr adapt`: self-contained codegen, no runtime dependency)
      + MCP server (`agr mcp`): `search_graphs / get_graph / instantiate / infuse_ability`.
- [x] **M4** — `agr adapt --target {crewai,autogen}` (two more self-contained codegen
      targets) and `agr compose` (sequentially chain two graphs, with a heuristic
      contract-compatibility check and `--allow-gaps` escape hatch).
- [x] **M5 / AGR v1.1 — composites.** Depth instead of length: `kind: subgraph`
      (inline expansion, depth-capped, cycle-detected), real `join` semantics with
      dead-branch settlement, executable `kind: human` gates, `error`/`compensate`
      edge kinds, per-node `retries`, declared `inputs`/`outputs` contracts, and
      opt-in verification-command execution. 22 composite graphs across five new
      motifs. The v1 scheduler was replaced wholesale against a
      [trace lock](tests/fixtures/v1_trace_lock.json) proving all 106 pre-existing
      cases execute byte-identically. Plan: [v2-agr-1.1.md](docs/plans/v2-agr-1.1.md) ·
      Audit: [v2-audit.md](docs/plans/v2-audit.md).
- [x] **M6 / AGR v1.2 — depth.** Execution frames (the blackboard gained a history),
      real `fan_out` cardinality with logged truncation, `aggregate` (majority /
      median / union / best), `kind: search` (bounded beam), scoped `memory`,
      enforced `state.schema`, and phase-scoped verification — which closes v1.1's
      deferral so a composite inherits its children's contracts. `ReplayRunner`
      makes `assert-live` reachable in CI from checked-in real-model recordings.
      17 graphs migrated off the decorative `parallel_group` label onto real
      fan-out. Plan: [v3-agr-1.2.md](docs/plans/v3-agr-1.2.md) ·
      Audit: [v3-audit.md](docs/plans/v3-audit.md).
- [x] **M7 / AGR v1.3 — live.** `triggers` + `agr triggers` (cron / GitHub Actions /
      webhook), `durability` + `agr eval --resume-from` (resume is replay over v1.2
      frames), and **enforced** `budget` caps. `approval.timeout` and
      `retries.backoff` were deleted rather than carried a third version unenforced.
      75 recordings across 3 models, with per-model results and
      [contract findings](docs/contract-findings.md).
      Plan: [v4-agr-1.3.md](docs/plans/v4-agr-1.3.md) ·
      Audit: [v4-audit.md](docs/plans/v4-audit.md).
- [x] **M8 / AGR v1.4 — connect the contracts.** A graph had two vocabularies with
      nothing checking they matched: **123 of 183 verification keys (67%) were
      produced by no declared node output**. One lint now closes that, and all 83
      graphs are migrated — declarations derived from the golden fixtures, with
      **zero asserts modified** (verified by parsing HEAD against the working tree).
      Contracts satisfied by no recorded model: **4 → 1**. Spec:
      [agr-v1.4.md](docs/agr-v1.4.md) · Plan: [v5-agr-1.4.md](docs/plans/v5-agr-1.4.md) ·
      Audit: [v5-audit.md](docs/plans/v5-audit.md).
- [x] **M9 / AGR v1.5 — every node declares.** v1.4's diagnosis was wrong, and the
      recordings said so: `ab-test-analysis` had both keys on *one* node, nothing
      joint about it. The real gap was **103 of 346 nodes (29%) declaring no outputs
      at all** — every one feeding a downstream node. Told only to "return the keys
      this step is responsible for", a live model answers that question literally
      and returns key *names* where values belong. All 103 now declare; `inputs` are
      checked against producers that can actually *reach* the consumer; the 6 genuine
      joint-precondition asserts get an advisory rather than new machinery.
      Spec: [agr-v1.5.md](docs/agr-v1.5.md) ·
      Plan: [v6-agr-1.5.md](docs/plans/v6-agr-1.5.md) ·
      Audit: [v6-audit.md](docs/plans/v6-audit.md).

- [x] **M10 / AGR v1.7 — the goal.** `state.inputs` had named what a caller must bring
      since v1.1, and **the runtime seeded none of it**: `run_graph` opened with
      `bb = {}`, so the linter vouched for values that never arrived and 31 of 83 graphs
      began work not knowing their subject. A model handed an empty board invents a
      plausible subject and answers about that — a well-typed answer to a question
      nobody asked. `run_graph(inputs=...)` closes the seeding half; a declared `goal`
      closes the other. A graph with `goal.required` and no goal executes **zero nodes**
      and reports what it needed, rather than guessing. Which 31 require one is derived
      from `state.inputs`, not hand-picked, with **zero asserts modified**. Ships
      `agr goal`, `--goal`, `goal_required` on the MCP search result, and a `/goal`
      command that asks the user rather than inventing one.
      Spec: [agr-v1.7.md](docs/agr-v1.7.md) ·
      Plan + outcome: [v11-goal.md](docs/plans/v11-goal.md).

- [x] **AGR v1.6 — provenance (skipped by the registry).** One lint, armed per graph:
      an assert that demands a citation, log id or file+line from nodes with no bound
      ability that could obtain one is a graph-authoring defect, not a model failure.
      No shipped graph declares `agr/v1.6`; the gap is reported through
      [contract-findings](contract-findings.md) instead of enforced. Spec, written after
      the fact in the 2026-09-04 audit: [agr-v1.6.md](agr-v1.6.md).
- [x] **M11 / AGR v1.8 — the claim.** The assert evaluator reached `eval()` with an
      empty `__builtins__`, which is not a sandbox: a downloaded graph could run code on
      `agr eval`, and `agr adapt` inlined the same hole into every generated module.
      Closed with an AST allow-list applied at validate time, at run time, and in the
      emitted prelude. Found on the way: the runner had been handing every node the
      assertions it was scored on. Now refused: a contract any model-driven node grades
      itself on (`_lint_self_graded`), a verifier with no `criteria`, prose in a
      `command`, a one-way effect with no compensating path, and a motif the topology
      does not have. All 560 recordings were retired because none said which spec they
      were scored against. Spec: [agr-v1.8.md](agr-v1.8.md) ·
      Changelog: [0.9.4](../CHANGELOG.md).
- [ ] **M12 — the gap audit.** Five read-only auditors, ten dimensions, 50 findings at
      `aa486fc`; 48 remediation items in seven phases with a dependency graph. Phases
      0-1 (onboarding, crashes, safety, change-gated evidence writes) and 2 (every
      README number generated and CI-checked; doc currency enforced by
      `scripts/check_doc_currency.py`) are landed on `audit-remediation`.
      Audit: [audit-gaps-2026-09-04.md](plans/audit-gaps-2026-09-04.md) ·
      Plan: [audit-gaps-remediation-2026-09-04.md](plans/audit-gaps-remediation-2026-09-04.md).

**Known limits, stated rather than buried:**

- **A graph+model cell frequently returns a different verdict on identical input** —
  **20%** of cells on `qwen3-coder:30b`, **51%** on `devstral:24b`, at 3 samples each. It
  is not one weak model: the second family was twice as unstable, and worse once the
  composites were included. Of the cells scorable on both, **57% land in different
  stability classes**; `incident-triage-router` is 0/3 on one model and 3/3 on the other.
- **✅ *satisfied on every model, every sample* went 50 → 13** as repeats arrived, and 🚫
  *satisfied by no model* went 14 → 5. Nothing broke: 37 graphs that looked clean had
  been measured once each. Four graphs have cross-family evidence of an unsatisfiable
  contract. **74 cells are still n=1.** [Full analysis](docs/plans/v12-variance.md).
- **13 cells cannot be scored at all.** `devstral:24b` reliably emits unparseable output
  for them, and a sample that fails to parse writes no record — so it shrinks the
  denominator instead of counting. The worst model/graph pairings are *excluded from*
  the percentages rather than *penalised by* them, and no amount of resampling fixes it.
- **Model replies that do not parse are counted as nothing.** Three graphs returned a
  JSON array where an object was required, or truncated mid-object.
  `clinical-protocol-lifecycle` produced ERROR, FAIL and PASS across three identical
  runs. The scoreboard has no column for this.
- Three local models, all small (7B–30B). Nothing is claimed about frontier models.
- **v1.7's re-record measured sampling noise, not the goal.** 31 graphs were re-recorded
  on `qwen3-coder:30b` with the goal seeded: 10 improved, 5 regressed. Since seeding a
  goal cannot break a passing graph, the regressions were resampled — **two graphs
  produced both a pass and a fail under identical input**, and three reversed. The
  registry-wide 14 → 11 therefore rests on single ungrounded samples from cells now
  shown to be unstable, and no improvement traced to a tool call. Read the unsatisfiable
  count as unmoved.
- Search graphs are tested against synthetic gradients, not a real scorer.

Of the 52 primitives, three are handcrafted with domain specialities
(`code-review-pipeline`, `verifier-swarm`, `cost-routed-research`) and the other 49 are
motif-template instantiations carrying real per-use-case contracts. The 22 composites
each declare an explicit phase list and I/O contract; 14 of them reference a primitive
by `ref` rather than restating it.

See [open issues][issues-url] for the full list of proposed graphs and known issues.

<p align="right">(<a href="#readme-top">back to top</a>)</p>
