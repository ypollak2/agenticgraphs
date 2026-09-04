# Audit: what is missing from agenticgraphs — 2026-09-04

Commit `aa486fc`. Brief: [audit-gaps-prompt.md](audit-gaps-prompt.md). Run as five
parallel read-only auditors (Claude Fable 5.1), two dimensions each, merged here.
Every finding cites `file:line` or a command that was actually run. Nothing in the
brief's "Already known" list is re-reported.

Baseline: `uv run agr validate` → 83/83 OK. `uv run pytest -q` (with `--all-extras`) →
413 passed, 1 xfailed, 91% coverage.

**Side effect of auditing, restored:** running `pytest`/`agr eval` rewrote three
`profile.json` date stamps and `.coverage` in the working tree. Reverted with
`git checkout`. That a read-only report generator writes to the evidence store is
finding D6-04.

**Corrections to the brief itself** (so the next audit does not chase them):
`~112 graph directories` is wrong (83 per-graph dirs; 182 counting `live/` subdirs);
`103 "declare"` in milestones.md is a v1.5 *node* metric, not a graph count;
`agr instantiate` does not exist, the CLI verb is `agr adapt` (see D5-06); tests are in
27 files, not 28.

---

## 1. Count reconciliation

| Metric | README | docs/milestones.md | Registry / CLI | Disk | Verdict |
|---|---|---|---|---|---|
| Graphs | 83 (badge, `README.md:136,603`), **52** (`:319,347,394,418`), **74** (`:488`) | 52 (M0 snapshot, `:9`) | `agr list \| wc -l` → 83; validate 83/83 | `find graphs -mindepth 2 -maxdepth 2 -type d` → 83 | **83.** Only hand-typed README prose disagrees. |
| Primitives / composites | 52 / 22 (`:418,431`) | 52 (M0) + 22 (M5) | no code field distinguishes them (`grep composite\|primitive src/` → 0) | 18 graphs contain `ref:` | Not a regenerable quantity. Frozen milestone text. |
| Motifs | 19 (badge, `:132,412`) | — | `gen_cards.py` emits 17 `P` nodes | `grep pattern: usecases/catalog.yaml \| sort -u` → 17 | **17.** `supervisor-hierarchy` and `escalation-ladder` have zero graphs; their cited examples carry other patterns (`catalog.yaml:31,283`). |
| Use cases | 131 (badge), **112** (`:395`), **123** (`:405,494`) | 112 (M0) | `audit_usecases.py` → 131 | — | **131.** |
| Domains | 15 (badge, correct); distribution at `:488-492` disagrees with generated chart at `:176-192` on 5 of 15 | — | 15 | — | Count sound, distribution prose stale. |
| Tests | 204/204 (badge, `:610`) | — | 413 passed (all extras); 390 + coverage FAIL (bare `uv sync`) | 345 `def test_` in 27 files | Badge stale by 2×. Set once in `40ab7c0`, never regenerated. |

Root cause: `gen_cards.py` and `gen_scoreboard.py` regenerate exactly two README
blocks (`<!-- graph-of-graphs -->`, `<!-- scoreboard -->`) and CI diffs only those.
Every other number is hand-typed and structurally invisible to CI.

---

## 2. Findings

Severity: **B** blocks-thesis · **T** degrades-trust · **H** hygiene. Effort S/M/L.
Ordered by severity, then effort ascending.

### Blocks-thesis

| id | dim | type | evidence | fix shape | eff |
|---|---|---|---|---|---|
| D4-02 | 4 | missing-lint | Ref cycles are not detected statically. Reproduced with two synthetic graphs `cat/a`↔`cat/b` (outside repo): `validate.lint_graph` reports no cycle; only `subgraphs.expand` raises `SubgraphError` (`subgraphs.py:109-111`), which `validate.py` never calls. Coverage shows `subgraphs.py:93,109-111,119-121` (all three `SubgraphError` branches) untested. | Walk the ref graph inside `lint_graph`; add a regression test. | S |
| D9-1 | 9 | missing-test | README Getting Started (`README.md:329-339`: `uv sync && uv run agr validate && uv run pytest -q`) **fails on a fresh clone**: 390 passed, 3 skipped, `Required test coverage of 90% not reached. Total coverage: 89.38%`, exit 1. Skips are the `adapters`/`mcp` extras. CI uses `uv sync --all-extras --frozen` (`ci.yml:12`) so it can never see this. `--all-extras` is mentioned only at `README.md:527`. | Change step 2 to `uv sync --all-extras`, or add a CI job that runs the documented path. | S |
| D6-01 | 6 | missing-evidence | `reports/self-graded.json` lists 16 open self-graded contracts; `agr validate` now finds 0. `_lint_self_graded` (`validate.py:152-197`) only matches bare-truthy reads. Two of the 16 were "fixed" by rewording: `returns-triage/graph.yaml:52` `output.assigned_disposition == output.expected_disposition` and `ticket-triage-swarm/graph.yaml:67` `output.assigned_queue == output.expected_queue`. In both, the verifier node declares **both** compared keys in its own `outputs:` (`returns-triage:34-37`, `ticket-triage-swarm:39-43`) and has no `inputs:` from external state. The verifier still manufactures both sides of its check. `reports/` is gitignored and no script generates `self-graded.json`. | Make the lint a provenance check (every free variable read by an assert must trace to a node with external `inputs:`), not a regex; commit and regenerate the findings file. | M |
| D4-01 | 4 | missing-lint | `ref` is an unversioned path (`spec/agr-graph.schema.json:94-98`); `subgraphs._resolve` loads whatever is on disk (`subgraphs.py:78-82`). The only lints are "ref resolves" and "phase declares verification" (`validate.py:538-544`). Nothing compares the phase node's `inputs`/`outputs` against the referenced primitive's current entry/terminal contract. A primitive can rename an output and every composite keeps validating. | Lint phase-node I/O against `subgraphs.entry_nodes`/`_terminals` of the resolved ref, or add a content-hash pin. | M |
| D4-03 | 4 | missing-feature | `expand()` (`subgraphs.py:188`) overrides only `apiVersion`, `nodes`, `edges`, `verification`, `termination`. A child's `goal`, `state`, `memory` never reach the parent. `run_graph`'s goal gate reads only top-level `doc["goal"]` (`harness.py:884-893`) and runs before `expand()` (`:908-911`). 9 of 14 composites hand-duplicate `goal.required: true`; nothing enforces it; `state.schema`/`memory` have no workaround. | Merge or require child `goal.required`, `state.schema`, `memory.scope` on the parent during `expand()`. | M |
| D5-01 | 5 | missing-feature | The graph-level `verification:` block is emitted into **no** adapter target. 30 `assert:` lines across 18 composites; `grep assert` over all 36 generated `.py` files → 0. `adapters.py` never reads `doc["verification"]`. Only the prose `termination.contract` survives as a docstring (`adapters.py:119-120`). | Emit `verification[].assert` as a post-run check using the `_safe_expr` guard already inlined for `when:`. | M |
| D5-02 | 5 | missing-feature | `fan_out` is silently dropped by every adapter. `vendor-comparison-matrix/graph.yaml:31-33` declares `fan_out: {over: vendor_docs}`; emitted LangGraph is one `g.add_node("fill", ...)` with a single edge, no `Send`. `adapters.py` has zero references to `fan_out`. Confirmed on 4 composites. | LangGraph: `Send()`-based map; CrewAI: flag as unsupported in a comment. | M |
| D2-01 | 2 | missing-feature | `bindings.BUILTINS` (`bindings.py:130-134`) binds 3 of 32 abilities. All of `_IRREVERSIBLE_ABILITIES` (`file_record`, `cut_release`, `shadow_write`, `backfill`; `validate.py:276-278`) plus `execute_step`, `run_suite`, `rollback`, `edit_files`, `sast_scan`, `secret_detection` have no binding. `ToolRunner.run` (`harness.py:651-656`) falls back silently to the plain `LLMRunner`. A node declaring `cut_release` cuts nothing; the model narrates a JSON object and that narration is the fact. Self-grading, one layer below the verification layer v1.8 fixed, ungated by any lint. | Bind the execute-risk abilities, or lint-refuse `risk: execute/write` abilities with no binding (or downgrade their risk label). | L |
| D3-01 | 3 | missing-feature | `parallel_group` is schema-declared and lint-enforced (`validate.py:335,356-358`; `inspect.py:74` counts them) but `run_graph` never reads it. The scheduler (`harness.py:969`) runs exactly one ready node per step. 89 graph files declare `parallel_group`. The lint vouches for parallelism the runtime never delivers. | Batch-run same-group ready nodes per step, or document serial-by-design and stop the lint implying concurrency. | L |
| D9-6 | 9 | missing-lint | Only two `<!-- begin/end -->` marker pairs exist in README; no script writes any of the 6 badges (`grep shield scripts/*.py` → 0). CI's staleness gate (`ci.yml:23-32`) diffs only generated blocks. Motif tables, "Library at a Glance", badges, and every number in section 1 above drift silently. "Quality is measured not claimed" (`README.md:71`) does not hold for the README. | `scripts/check_readme_counts.py` asserting every hard-coded count and badge against registry/catalog/pytest; wire into the CI staleness step. | M |
| D10-1 | 10 | roadmap | Roadmap item 1 (re-record evidence) will produce new numbers that face the identical drift the moment they are pasted into prose. No roadmap item generalizes the staleness gate. | Roadmap item 4: generated-block coverage for every number-bearing README section. | — |
| D10-2 | 10 | roadmap | Items 1-3 need a contributor who can run the suite. D9-1 shows the documented path is red on a fresh clone and CI never exercises it. | Roadmap item 5: Getting Started passes as written, enforced by CI. | — |
| D10-3 | 10 | roadmap | `docs/milestones.md` stops at M10/v1.7 (`grep M11 docs/` → 0) though v1.8 shipped 89 minutes after its last edit; five spec docs carry no superseded banner. Nothing forces doc currency at a spec bump, so v1.9 will lag the same way. | Roadmap item 6: doc-currency check at spec-bump time (banner + milestones entry required to merge). | — |

### Degrades-trust

| id | dim | type | evidence | fix shape | eff |
|---|---|---|---|---|---|
| D1-01 | 1 | missing-feature | `on_partial: continue` (default) merges failed shards as `None` (`harness.py:1172-1185`). `architecture-decision-tournament` and `sales-call-scorer` feed that list into `aggregate: {op: best\|median}`. Verified: `_AGG["best"]([3, None, 5])` and `_AGG["median"](...)` (`harness.py:1114-1134`) raise `TypeError`. One failed shard crashes the run. | Filter failed shards before `_AGG`, and document what `continue` means. | S |
| D3-02 | 3 | missing-feature | No per-node deadline in `run_graph`. Worst case per node ≈ 4 tool rounds × 4 HTTP attempts × (180s + backoff) ≈ 51 min (`harness.py:404-431,625,661`); budgets are checked only between steps (`:955-968`). `bindings._read_diff` (`bindings.py:83`) calls `subprocess.run` with **no `timeout=`** and no exception handling, unlike `_run_command` four lines above. | Add `timeout=` to `_read_diff` (S); per-node deadline in `run_graph` (M). | S/M |
| D3-06 | 3 | missing-feature | `budget.usd_max` is real only for `gpt-4o`/`gpt-4o-mini` (`harness.py:836-839`); every other model, including every local model the evidence base is recorded on, uses a flat `_EST_USD_PER_NODE = 0.002` (`:845`). The cap is meaningless for the configuration actually run. | Extend `_TOKEN_PRICES` to the recorded local models (0 or hosting cost). | S |
| D4-04 | 4 | missing-lint | `compose_by_reference` (documented "Preferred", `compose.py:150-157`) never validates its output, unlike `compose()` (`:287-291`). Reproduced: `agr compose invoice-reconciliation competitive-intelligence --mode subgraph -o x.yaml` succeeds; `agr validate x.yaml` fails twice ("embeds subgraph ... but the graph declares no verification"). Also hardcodes `apiVersion: agr/v1.1` (`compose.py:164`). | Validate inside `compose_by_reference`; derive `apiVersion`. | S |
| D5-04 | 5 | missing-feature | `kind: human` and `kind: verifier` are indistinguishable from LLM nodes in LangGraph and CrewAI output; only `emit_autogen` reads `kind` (`adapters.py:266`). `feature-delivery-lifecycle`'s `release-approval` human gate emits as a bare `NotImplementedError` stub. | Emit a `# HUMAN GATE` / `# VERIFIER` marker and stricter default in both emitters. | S |
| D5-06 | 5 | missing-feature | MCP `instantiate` hardcodes `target="langgraph"` and raises for anything else, citing "(M3)" (`mcp_server.py:53-61`); CrewAI and AutoGen shipped at M4 (`milestones.md:18`) and are CLI-exposed. CLI verb is `adapt`, MCP tool is `instantiate`, no alias. | Add `target` param wired to `emit_crewai`/`emit_autogen`; align verb names. | S |
| D6-02 | 6 | missing-evidence | `reports/a4-stale-recordings.json` covers 560 rows, all with the pre-move `evals/` prefix (0 exist on disk); current recordings number 1109 under `graphs/*/live/`. `audit_recordings.py` computes the correct path (`:105`) but is in neither `Makefile` nor CI, exits non-zero on a flip (`:216`) that nothing checks, and its output is gitignored. | Wire into `make regen` and CI, or stop shipping the JSON. | S |
| D6-03 | 6 | missing-lint | `gen_contract_findings.py` is absent from `make regen` (`Makefile:14-17`) and CI's stale-docs diff (`ci.yml:23-32`). `docs/contract-findings.md:3-4` claims "never hand-maintained"; nothing enforces it. | Add to `make regen` and the CI diff list. | S |
| D7-01 | 7 | safety | `run_server` (`mcp_server.py:102-114`) adds no authentication, only `host=127.0.0.1`. With `AGR_AUTONOMOUS=1` in a long-running server's environment (e.g. the LaunchAgent at `~/Library/LaunchAgents/com.ypollak2.agenticgraphs-mcp.plist`), any local process can call `infuse_ability(persist=true)` and land a commit on `auto/mutations`. | Shared-secret header check on the HTTP transport, independent of the autonomy env vars. | S |
| D8-01 | 8 | missing-test | `run_server`/`main` have zero coverage (`mcp_server.py:104-114,118` missing). The `127.0.0.1` binding the safety story rests on is asserted in a comment, never a test. | Test that monkeypatches `server.run` and asserts `host == "127.0.0.1"` on both SDK code paths. | S |
| D8-03 | 8 | missing-test | README badge `tests-204/204` (`README.md:610`) vs 413 passed. No script regenerates it. | Drive the badge from `pytest --collect-only`. (Subsumed by D9-6.) | S |
| D9-2 | 9 | missing-doc | README's "Every number is checkable" section (`:391-396`) shows `agr list \| wc -l  # 52 graphs`. Run verbatim: 83. | Regenerate or delete the comment. | S |
| D9-3 | 9 | missing-doc | `docs/agr-v1.{1,2,4,5,7}.md` are linked from `README.md:406`; none mention v1.8 or "superseded" (`grep` → 0). | Generated "Superseded by" banner on every non-current spec doc. | S |
| D9-4 | 9 | missing-doc | `docs/milestones.md` ends at M10/v1.7; no M11 anywhere; last edited 89 min before `agr-v1.8.md` landed. | Add M11; require a milestones entry per new spec doc. | S |
| D9-5 | 9 | missing-doc | Domain distribution prose (`README.md:488-492`) contradicts the generated chart (`:176-192`) on 5 of 15 domains. | Delete the prose; the chart covers it. | S |
| D9-7 | 9 | missing-doc | `uv run agr mcp` after a bare `uv sync` crashes with a raw `ModuleNotFoundError: No module named 'mcp'` traceback (`mcp_server.py:25`, `cli.py:206`). | Catch the ImportError and print the install hint. | S |
| D0-1/3 | 0 | missing-doc | Three graph counts (83/52/74), three use-case counts (131/112/123) in one README; 52/22 and 112 are M0/M5 announcement text never revised (`git log -S`). | Single-source every count from generated blocks. | S |
| D0-2 | 0 | missing-lint | 2 of 19 claimed motifs have no backing graph, shipped or backlog. | Seed one entry each or drop them from table and badge. | S |
| D1-02 | 1 | missing-lint | 39 nodes set `retries.max > 0` on a node with a `write`/`execute`-risk ability (e.g. `data-quality-audit/work`, `vuln-remediation-lifecycle/reproduce`). No concept of idempotency anywhere (`grep idempotent src/ spec/ docs/ abilities/` → 0). `harness.py:1032` re-runs regardless. A partially-applied `run_command` gets re-run. | Lint `retries.max>0` + write/execute ability, or add `retries.idempotent`. | M |
| D2-02 | 2 | missing-feature | `abilities/run_command.yaml` declares `binding.ref: agenticgraphs.bindings:run_command`; that symbol does not exist (only `_run_command`). `bindings.available()` (`:146-164`) never reads `binding` at all; it dispatches by name against `BUILTINS`. The schema's `binding.{kind,ref}` field, which the module docstring calls "the seam", is unread and wrong even for the 3 working abilities. | Resolve `binding.ref` dynamically, or drop the field and document `BUILTINS` as truth. | M |
| D3-03 | 3 | missing-feature | No error taxonomy. `extract_json` `ValueError` (`harness.py:180-216`) and `HumanGateRequired` (`:226-233`) escape `run_graph` uncaught; neither `evalcmd.py` nor `cli.py` catches them. Only `record_live.py:200-203` does, as a bare `except Exception` into one untyped string. This is the mechanism behind "13 cells never parse", and it cannot tell parse failure from refusal from crash. | `parse_failure`/`gate_refused` fields on `RunReport`; catch inside `run_graph`. | M |
| D5-03 | 5 | missing-feature | `retries.max` (schema says "Enforced", `agr-graph.schema.json:135-146`) and `approval.contract`/`on_timeout` are never read by `adapters.py`. 7 composites declare retries, 6 declare approval; all emit as plain stubs (e.g. `feature-delivery-lifecycle__langgraph.py:132-134`). | Retry wrapper; embed `approval.contract` as a pre-proceed assertion; `on_timeout` as a branch. | M |
| D5-05 | 5 | missing-feature | CrewAI `Process.sequential` cannot take loop-back `when:` edges; the condition survives only as English in `Task.description`. A verifier-retry graph compiles to source structurally incapable of retrying, with no comment. | `Process.hierarchical`, or emit a "loop dropped" comment. | S doc / L fix |
| D6-04 | 6 | evidence-integrity | `gen_contract_findings.py` calls `eval_graph()` which **unconditionally rewrites `profile.json`** with today's date (`evalcmd.py:134,201`). Regenerating a report perturbs all 83 evidence files; `Makefile:22` excludes them from the stale check for that reason. The `date` field cannot mean "when captured". This audit reproduced it (three files reverted). | Split `eval_graph` into pure compute + explicit `write_profile` that writes only on content change. | M |
| D7-02 | 7 | safety | `docs/autonomy.md:82-87`: `agr optimize --apply --autonomous` bypasses `commit_autonomous_mutation` and writes to the live checkout, while MCP persist is isolated to `auto/mutations` (`autonomy.py:84-116`). One flag, two blast radii. | Route optimize through the same isolation, or split the env var. | M |
| D7-04 | 7 | missing-feature | MCP exposes 4 tools; CLI has `validate`, `list`, `profile`, `eval`, `goal`, `optimize`, `compose`, `triggers` (`cli.py:27-89`) none of which are reachable over MCP. No diff tool on either surface. | Add `validate_graph`, `run_graph`, `list_abilities`, `get_profile` MCP tools. | M |
| D8-05 | 8 | missing-test | `test_runner_transport.py` and `test_tool_grounding.py` never load a registry graph; real `abilities:` lists never flow through `bind_for`/`invoke` in any test. | One integration test over a real graph with `allow_mutating=True`. | M |

### Hygiene

| id | dim | type | evidence | fix shape | eff |
|---|---|---|---|---|---|
| D1-04 | 1 | missing-lint | `_RUNTIME_KEYS` (`validate.py:73`) allows `shards_failed` but not `shards_processed`, which `_fan_out` also publishes (`harness.py:1181`). | Add it. | S |
| D1-05 | 1 | missing-lint | Reachability (`validate.py:705-719`) counts `error`/`compensate` edges; a verifier reachable only via a failure edge passes. 0/83 affected today. | Document as intentional or add a flow-only variant for verifiers. | S |
| D1-06 | 1 | missing-doc | `spec/agr-graph.schema.json:4` title still says "AGR Graph v1.7"; enum and fields are v1.8. | Bump the title. | S |
| D1-03 | 1 | missing-doc | No `docs/agr-v1.3.md` or `agr-v1.6.md`, though both shipped enforced features (`triggers`/`durability`/`budget`, saga lint at `validate.py:666-684`; provenance lint at `:959-970`). | Write both in the existing format. | S |
| D2-03 | 2 | missing-feature | `optional_abilities` set in 12/34 speciality files, read by 0 lines of code; `prompt_seed` set by 0, read by 0. | Wire `optional_abilities` into the lint or drop it. | S |
| D3-04 | 3 | missing-doc | `durability.checkpoint`/`resume_from` (`harness.py:938-946`, `agr eval --resume-from`) used by 6 graphs, absent from `docs/agr-v1.8.md` (`grep resume\|checkpoint\|durability` → 0). No journal-shape contract. | Document the journal line schema and version stability. | S |
| D3-05 | 3 | missing-evidence | `docs/traces/README.md` index shows "100%" for all 83 with no caveat; every trace is `MockRunner` (`gen_traces.py:18-32`). The per-page "(mock, provisional)" qualifier is stripped from the roll-up. | Carry the qualifier into the index. | S |
| D4-05 | 4 | missing-feature | `agr compose -o` writes a valid `graph.yaml` but scaffolds no `cases.yaml`, registry entry, or `live/`; composition output can never earn an eval verdict without manual onboarding. | Optional scaffold, or document the manual steps. | M |
| D7-03 | 7 | missing-lint | `infuse_ability(persist=False)` runs `validate_schema` only (`mcp_server.py:83-97`); `persist=True` runs the full lint. Not exploitable today; same asymmetry shape the RCE commit warned about. | Call `lint_graph` in both branches. | S |
| D8-02 | 8 | missing-test | The `persist=True` success path is untested through the MCP wrapper (`mcp_server.py:74-81` uncovered); only `mutate.infuse_autonomous` is tested directly. | Test through the registered tool with `AGR_AUTONOMOUS=1`. | S |
| D8-04 | 8 | missing-test | `evalcmd.py`, `subgraphs.py`, `triggers.py` have no dedicated test file; exercised only incidentally by `test_v1x.py`. | Add the three files. | S |
| D8-06 | 8 | missing-test | Only loose bounds on registry size (`>= 50` in `test_graphs_scale.py:5-9`, `>= 83` in `test_cli.py:23`); nothing pins an exact count. | One exact-count test from a single source of truth. | S |
| D0-4 | 0 | missing-feature | No `primitive`/`composite` field exists, so the 52/22 split cannot be regenerated even if wanted. | Derive from `kind: subgraph` presence at doc-gen time. | M |

---

## 3. Top 5 gaps

1. **Adapters drop the contract (D5-01, D5-02, D5-03, D5-05).** "Verification is
   structural" holds only inside `harness.py`. The moment a graph is instantiated for
   LangGraph or CrewAI, every assert, fan-out, retry, and approval gate vanishes and
   only a prose docstring remains. The README sells instantiation as the product.
   Smallest close: emit `verification[].assert` as a terminal check function using the
   `_EMITTED_GUARD` allow-list that already ships in the prelude. One function in
   `adapters.py`, one test that greps the output for each assert.

2. **Abilities are narrated, not bound (D2-01, D2-02).** 29 of 32 abilities, including
   every irreversible one, fall back to the plain LLM runner. `cut_release` and
   `file_record` are model prose. The `binding.ref` field is dead and wrong. Smallest
   close: a lint that refuses `risk: execute|write` with no entry in `BUILTINS`, which
   will fail 80-odd graphs and make the gap visible instead of implicit.

3. **The self-graded lint was evaded, not satisfied (D6-01).** Sixteen findings went to
   zero by rewording asserts so the same verifier still produces both sides of its own
   comparison. The lint is a regex; the property is provenance. Smallest close: track
   which node produced each key an assert reads and flag asserts whose every input
   comes from the verifier itself. `_upstream_outputs` (`validate.py:801-824`) already
   has the walk.

4. **The runtime lint vouches for things the runtime does not do (D3-01, D1-01,
   D3-02).** `parallel_group` is enforced and never executed; `on_partial: continue`
   crashes on the first failed shard in two shipped graphs; a node can run for 51
   minutes with no deadline. Smallest close: the `None` filter before `_AGG` is a
   two-line fix and removes a crash in a shipped graph today.

5. **The README is the one artifact "quality is measured not claimed" does not cover
   (D9-6, D9-1, D0-*).** Six independent numbers are stale, the Getting Started path is
   red on a clean clone, and CI is structurally blind to both. Smallest close: change
   `uv sync` to `uv sync --all-extras` in step 2 (one line, unblocks every new
   contributor), then a counts-check script in the existing CI staleness step.

Composition (D4-01, D4-02, D4-03) is a close sixth: composites are where the README
says the thesis lives, and they are the least-linted part of the registry.

---

## 4. Checked and found sound (do not re-check)

- `risk_surface` is computed from `abilities/*.yaml`, never hand-declared (`inspect.py:41-80`).
- `budget.usd_max`/`steps_max` genuinely halt a run (`harness.py:955-965`).
- `state.inputs` producer check is a real reachability walk (`validate.py:650-664,801-824`).
- Every ability file is used by ≥1 graph and vice versa (32/32); same for specialities (34/34).
- The 3 bound abilities do real work with real failure paths; none are always-succeed stubs.
- All 234 `assert`/`when` and 13 `score`/`contract` expressions pass `safeexpr.check`.
- The v1.8 RCE fix covers all three claimed entry points (`validate`, `harness.safe_eval`, emitted `_EMITTED_GUARD`); allow-list parity is pinned by tests.
- `resolve_command` uses `shlex.split` + `subprocess.run` without `shell=True`; placeholder values can shift argv, not spawn a shell.
- MCP `name` resolution goes through `registry.graph_dir()` by equality, no path traversal.
- `infuse_ability(persist=True)` cannot smuggle an unknown ability name (double-checked in `mutate.py:65-67,91-93`).
- `_Readiness` distinguishes dead branches from deadlock; resume-from-journal reuses the live `_fire` helper so replays cannot diverge.
- `_reconcile_output` only moves values a node produced and logs each move.
- Fan-out truncation is reported, never silent.
- `compose()` (inline mode) validates its own output.
- `subgraphs.expand` depth/cycle guards work at runtime.
- All 18 composites compile to both LangGraph and CrewAI (36/36 exit 0); subgraph expansion precedes emission.
- Exactly three adapter targets are promised and exactly three exist.
- Every one of 83 graphs has a non-empty `live/`; "83 recorded" is true.
- Graph count 83 agrees across `agr list`, `agr validate`, disk, and `registry.py`.
- Use-case count 131, backlog 48, domains 15, and `pyproject` 0.9.4 vs CHANGELOG all agree.
- The two generated README blocks are regenerated and CI-diffed correctly.
- `uv sync` itself resolves cleanly on a fresh clone; `agr validate` is byte-reproducible there.
- `uv run pytest -q` with extras: 413 passed, 1 xfailed, 91% coverage.

---

## 5. UNVERIFIED

- **Origin/CORS validation on the streamable-http transport.** `mcp` 1.28.1 is pinned; whether it rejects forged `Origin` headers on loopback was not traced into site-packages. If not, a browser page could reach `127.0.0.1:8765` and compound D7-01.
- Whether `gen_contract_findings.py` can distinguish "never recorded" from "every reply failed to parse": `scripts/gen_contract_findings.py:26-28` drops both identically. Not reproducible without writing to the repo.
- Whether `emit_autogen` drops `verification`/`fan_out`/`retries`/`approval` like the other two emitters. Strongly implied by code; autogen output was not sampled.
- Whether any `kind: subgraph` composite would trip D4-01 today. Requires editing a live primitive.
- Whether `_lint_stall` has false negatives on 3+ node retry chains.
- Whether a real 51-minute node (D3-02) has occurred in the recorded corpus.
- Whether any unattended entry point (cron, script) calls `agr optimize --autonomous` today.
- Whether the PyPI path `uvx --from "vitruvian-graphs[mcp]" agr list` (`README.md:319-320`) works as documented.
- Whether the 52/22 split was ever mechanically true at the M0/M5 commits.
- A line-by-line diff of every MUST/SHOULD in all eight spec docs against every lint was not exhaustive; D1-03..06 came from targeted checks.
- Stale-number mentions in `CARDS.md`, `CONTRIBUTING.md`, `docs/agr-bindings.md` were not individually swept.
