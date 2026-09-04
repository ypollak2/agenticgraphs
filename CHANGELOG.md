# Changelog

## [Unreleased] — the gap audit, remediated

Fifty findings from a five-auditor read-only audit (`docs/plans/audit-gaps-2026-09-04.md`),
forty-eight remediation items in seven phases, all landed. The headline gaps and what
closed them:

- **The README was the one artifact "quality is measured not claimed" did not cover.**
  `scripts/check_readme_counts.py` owns every badge and count; `check_doc_currency.py`
  refuses a spec bump without a milestone entry and superseded banners; `reports/`
  and `docs/contract-findings.md` are regenerated and diffed in CI; `profile.json`
  is written only when its content changes.
- **Abilities were narrated, not bound.** `binding.ref` resolves or fails validate;
  a node whose execute/world-write ability has no binding must say `unbound_ok`
  (38 graphs do); a retried non-idempotent ability must say `reissue_effects`.
- **The self-graded lint had been evaded by rewording.** It now asks who produces
  each side of a comparison; the 16 graphs it recovered were fixed by declaring the
  caller's reference as input, moving thresholds to `state.inputs`, or moving the
  reference upstream. A node can no longer overwrite what the caller supplied.
- **Composites promised what their children never produced.** `maps` declares the
  rename and `_lint_phase_contract` checks it; `expand` carries `goal`, `state` and
  `memory` up; `agr compose --scaffold` writes an evaluable bundle.
- **Generated code dropped the contract.** LangGraph/CrewAI/AutoGen modules carry
  `check_contract`, fan-out, retries, and marked human gates.
- **Runtime truth.** Parse failures, refused gates and timeouts are `RunReport`
  fields; `timeout_s` bounds a node; `parallel_group` runs concurrently (`rounds`);
  a failed shard no longer crashes `median`/`best`.
- **Safety.** `AGR_MCP_TOKEN` guards the HTTP transport and is mandatory when
  autonomous; `optimize --autonomous` commits to `auto/mutations` like every other
  unattended write; six MCP tools (`validate_graph`, `run_graph`, `list_abilities`,
  `list_specialities`, `get_profile`, `diff_graphs`).

## [0.9.4] — the claims get checked, and the evidence gets thrown away

Two things happened. A security audit found the evaluator was not a sandbox, and
closing it exposed that most of what this registry asserted about itself was
unverified — including, in one case, by the runner handing every node the answer.

### The evaluator was not a sandbox

`edges[].when` and `verification[].assert` reached `eval()` with
`{"__builtins__": {}}`. That is not a sandbox: `().__class__.__bases__[0]` walks
back to `subprocess.Popen`. Any downloaded `graph.yaml` ran arbitrary code on
`agr eval`, with no opt-in, no warning, `agr validate` reporting `OK`, and the
same hole inlined into every module `agr adapt` generated. Closed by an AST
allowlist enforced at the gate, at run time, and inside generated code.
See [SECURITY.md](SECURITY.md) — the exposure was checkouts, not a package index;
nothing was ever published.

Fixing it surfaced a bug of the same age: the namespace was passed as *locals*, so
every **nested** quantifier raised `NameError` from the comprehension's own scope.
No contract in this registry could quantify two levels deep, and single-level
asserts hid it completely.

### The runner was telling each node the answer

Every prompt carried `Downstream assertions that must hold: [...]`, and the node
was then scored on exactly those asserts. 31 of 117 asserts were a bare truthy
read; 16 read a flag the graph's own model-driven node wrote. **Every live number
this project has ever published came from runs conducted that way.**

The assert text is gone from the prompt. What replaces it is `criteria` — a
required rubric on every verifier, saying what the claim MEANS in the domain
rather than which flag to set.

### What is now checked that was not

| Rule | Refuses | Found |
|---|---|---|
| `_lint_self_graded` | a contract the model grades itself on | 16 |
| `_lint_criteria` | a verifier with no rubric | 72 |
| `_lint_motif` | a graph declaring a motif its topology lacks | 14 |
| `_lint_commands` | prose in the `command` field | 1 |
| `_lint_irreversible` | a one-way effect with no compensating path | 3 |
| `safeexpr` | any construct outside a small allowlist | the RCE |

`_lint_motif` deserves a note: ten graphs called themselves `parallel-swarm` while
being a linear three-node chain, including `verifier-swarm` — the graph the README
uses to explain what a swarm is.

### The retry loops never ran

`edge_true` catches every exception and returns `False`, so an edge guarded on a
key nothing produces is not an error — it is an edge that is never taken. **52
guards across 43 graphs were in that state.** Every `verify_failed and attempts <
3` retry, every `<node>_failed` compensator, every `revision_requested` review
loop. The registry advertised bounded retries, escalation and saga compensation,
and in a real run it had none of them.

Every golden case passed throughout, because a fixture hands the key over. Only a
live run reaches the guard with a blackboard a model wrote, which is why this
survived until the first v1.8 recording sweep found it.

v1.7 found exactly this for `attempts` — "48 edge guards read it and nothing
produced it… every bounded retry loop silently failed closed" — fixed that one
name, and left the hole open for every other key.

The rule the spec was missing, now written down:

> **A model-written flag may drive control flow; it just may not be the thing the
> contract checks.**

Routing on a model's judgement is what a router *is*. Grading a model on its own
judgement is what v1.8 refuses. Those had never been distinguished, so removing a
self-graded flag from a contract also removed it from the node's outputs and
killed the edge reading it — `regulatory-filing-lifecycle` stopped being able to
reach its human gate at all. After the fix it runs six steps, exhausts its bounded
retry against a model that genuinely cannot reconcile the figures, and fails
honestly. Before, it ran two and stopped.

`_lint_flow_keys` and `_lint_runtime_keys` enforce both halves; the second exists
because the obvious fix — letting the node declare `attempts` — lets a fixture pin
the counter so the loop never terminates.

### 83 graphs are now 83 graphs

Stripping the strings that are free to differ, **36 of 83 were byte-identical to
another**, and 83 graphs were 40 shapes. `clinical-literature-triage` and
`incident-triage-router` differed in four strings; the healthcare graph had nodes
called `branch-simple` and `branch-complex` and contained no healthcare. Now 83
distinct topologies, 0 clones — each remaining pair differentiated by the step its
domain actually needs, not by renaming.

### All 560 recordings retired

Prompt change, sampling change, and 16 replaced contracts invalidate every one of
them at once. They are stamped and kept, not deleted — the record of what was
measured is the evidence the correction was needed — and excluded from every
number. **Live coverage reads 0 of 83, and that means pending re-recording.**

They had to be retired *wholesale* because none said which spec it was scored
against or how the model was sampled. Recordings now carry both, so the next spec
change retires precisely what it invalidates.

Two more things the retirement exposed:
- `record_live.py` recorded `cases[0]` only. For the project's whole life,
  "83 of 83 graphs recorded" meant *one case each* — and the cases worth measuring
  are the ones written second, the branch a model gets wrong.
- The router migration seeded its reference tables with the placeholder
  `"<ownership_map supplied by the caller>"`. With nothing to read, a model writes
  the same value into both sides of the comparison and passes. Real tables now,
  with a trap case in each.

### Also

- `uv.lock` was gitignored and untracked while CI ran `uv sync`; committed, with
  `--frozen` in both workflows.
- ruff + mypy adopted and in the gate. The source carried ten `# noqa` suppressions
  for a linter that had never run — one of them on the `eval` above. 152 findings
  to zero, including four real defects (dead `super()._prompt()` call, a
  `find_graph` None-deref, shadowed loop variables, and `ToolRunner.root` serving
  as both working directory and ability registry — which silently unbound every
  ability when pointed at a target repo).
- Executable verification commands 1 -> 20. The one that existed was prose.
- Tests 266 -> 393, coverage floor at 90%.
- `claims.txt`, a saved copy of example.com's HTML, deleted.

## [0.9.3] — instability is the setup, not the model

v0.9.2 found 20% of `qwen3-coder:30b` cells returning different verdicts on identical
input, and asked whether that was the model or the harness. A second family answers it.

| | `qwen3-coder:30b` | `devstral:24b` |
|---|---|---|
| stable pass (3/3) | 57 | 17 |
| stable fail (0/3) | 9 | 10 |
| **unstable** | **16 (20%)** | **23 (46%)** |
| cells scored | 82 | 50 |

**Not the model — the second family is worse.** Of 49 cells scorable on both, **28
(57%) fall into different stability classes**.

`incident-triage-router` is 0 of 3 on `qwen3-coder:30b` and **3 of 3 on
`devstral:24b`**. v0.9.2 listed it under "genuinely unsatisfiable — 0 of 3, not 0 of
1". It is not unsatisfiable, it is model-specific, and one model at n=3 could not tell
the difference. That claim is marked superseded in place rather than deleted.

**One graph now has cross-family evidence of an unsatisfiable contract:**
`flaky-test-reflexion`, 0 of 6 across two families.

| | before repeats | qwen3 n=3 | + devstral n=3 |
|---|---|---|---|
| 🚫 satisfied by no model | 14 | 8 | **6** |
| 🎲 same model, different answer | 2 | 18 | **37** |
| ✅ satisfied every model, every sample | 50 | 40 | **24** |

The ✅ column halving is the headline: 26 graphs that looked clean had been measured
once each.

### Added

- `devstral:24b` as a fifth model column, 3 samples on 50 of 83 graphs.
- Round 2 analysis in `docs/plans/v12-variance.md`.

### Fixed

- `scripts/record_live.py` batched all output and printed it only on completion, so a
  terminated sweep lost every result — 75 completed runs left no record beyond the
  recordings themselves. Results now stream with `flush=True`, making a long run both
  resumable and observable. This is the second defect of the same shape in this file:
  the recorder handled the happy path and discarded evidence on everything else.

### Known, unfixed

- `devstral:24b` reached 3 samples on 50 of 83 cells. The 25 unfinished are the heavy
  composites (~10 min each); three background runs were terminated part-way. Its 46% is
  measured on a set skewed toward primitives.
- Unparseable replies reduce `n` rather than counting as anything. `devstral:24b`
  emitted markedly more, including `float('inf')` — Python, not JSON. Pass / fail /
  unsatisfiable still has no room for "the model did not emit parseable output".
- All runs made 0 tool calls. Stability is not truth: a stable 3/3 with no tool call is
  a model that reliably says the same thing, not a model that is right.

## [0.9.2] — single samples mislabelled flaky graphs as unsatisfiable

v0.9.1 concluded that the goal re-record had measured sampling noise. This measures
the noise: 3 samples of all 83 graphs on `qwen3-coder:30b`, tools off — 249 runs.

| cell verdict | count | share |
|---|---|---|
| stable pass (3/3) | 57 | 70% |
| stable fail (0/3) | 9 | 11% |
| **unstable** | **16** | **20%** |

**One cell in five returns a different verdict on identical input.**

Registry-wide, once cells had repeats: 🚫 satisfied by no model **14 -> 8**, 🎲 same
model different answer **2 -> 18**.

The 🚫 count did not fall because anything improved. Six graphs were labelled on one
unlucky draw and actually pass 1-2 times in 3: `clinical-literature-triage` (67%),
`literature-review-swarm` (67%), `docs-code-sync-audit` (67%), `incident-lifecycle`
(67%), `product-listing-pipeline` (67%), `framework-migration` (33%).

`literature-review-swarm` was filed under 🔌 *unsatisfiable by construction* — "needs a
paper corpus". It passes 2 of 3 times. Either that label is wrong or those passes are
fabrication, and one sample could not tell you which.

Nine graphs failed 0 of 3, which is what evidence of an unsatisfiable contract actually
looks like. 73 cells remain at n=1 and no claim should be drawn from them.

All 249 runs made 0 tool calls. Stability and truth are different axes: a graph can sit
at a stable 3/3 and still be fabricating. `assert-grounded` matters more, not less.

### Added

- 3-sample coverage for 82 of 83 graphs on `qwen3-coder:30b`.
- `docs/plans/v12-variance.md` — the full analysis.

### Fixed

- `scripts/record_live.py` wrapped its entire sample loop in one `try`, so the first
  unparseable reply discarded that graph's remaining samples — leaving three graphs at
  n=1 in a run whose purpose was to remove n=1. Now per-sample.

### Known, unfixed

- Unparseable model replies are counted as neither pass nor failure. Three graphs
  returned a JSON array where an object was required, or truncated mid-object;
  `clinical-protocol-lifecycle` produced ERROR, FAIL and PASS across three identical
  runs. The scoreboard has no column for this, and `feature-delivery-lifecycle` sits at
  n=1 because two of its three samples were unparseable.

## [0.9.1] — the re-record measured noise, not the goal

v0.9.0 seeded a goal and deferred the question of whether it mattered. 31 graphs
re-recorded on `qwen3-coder:30b`, goal on the board, tools off to match the baseline:

| | |
|---|---|
| improved (0.0 -> 1.0) | 10 |
| regressed (1.0 -> 0.0) | **5** |
| registry-wide unsatisfiable | 14 -> 11 |
| improvements that traced to a tool call | **0** |

Seeding a goal has no mechanism for *breaking* a graph that passed, so the five
regressions were resampled twice each with identical inputs:

- `architecture-decision-tournament`, `book-editing-pipeline` — reversed to PASS
- `onboarding-plan-builder`, `red-team-blue-team-hardening` — **PASS and FAIL, same
  model, same input, same session**
- `invoice-reconciliation` — consistently failing

A cell that flips on resampling cannot evidence a change between runs. The 10
improvements and the 5 regressions are one phenomenon, and the goal is not it.
**Read 14 -> 11 as unmoved.**

The registry's stated limit — one sample per cell — turns out to be the whole result
rather than a footnote. 150 of 158 cells are still n=1. Repeated sampling, not another
feature, is the next measurement.

### Added

- 31 re-recorded `qwen3-coder:30b` runs carrying the seeded `inputs`, plus second
  samples for the five resampled graphs (flaky cells: 2 -> 4).

### Fixed

- `scripts/record_live.py` never passed entry inputs to `run_graph`, so every
  goal-required graph would have recorded the refusal gate instead of the model. The
  recording payload now also stores the `inputs` it was made under — a recording that
  does not say what was on the board cannot be compared against one made under
  different entry state.
- `scripts/derive_goals.py` reconciled golden cases only when the graph itself changed,
  so re-running it over an already-migrated registry left every case without a goal.

## [0.9.0] — the goal

`state.inputs` named what a caller must bring at entry from v1.1 onward. **Nothing
ever supplied it.** `run_graph` opened with `bb = {}` and had no parameter for entry
inputs; no eval case passed any. Meanwhile `validate.py` trusted the declaration and
`compose.py` read it for compatibility — so the linter vouched for values that never
arrived, and 31 of 83 graphs began work not knowing their subject.

That is the anti-pattern v1.3 deleted `approval.timeout` over, surviving five versions
in a field nothing read.

| | before | after |
|---|---|---|
| graphs declaring `state.inputs` | 31 | 31 |
| ...that actually receive them | **0** | 31 |
| graphs that refuse without a goal | 0 | 31 |
| assert expressions changed | — | **0 of 118** |

A graph with `goal.required` and no goal executes **zero nodes** and returns
`goal_missing` carrying what it needed. It does not guess.

**Not a claim about quality.** Seeding a goal makes a contract easier to satisfy, not
more truthful — v10 measured exactly this for typed scalars (3 graphs moved, 1
grounded). No re-record has been run, so nothing here says whether a goal moves any of
the 14 contracts no model satisfies. `assert-grounded` stays orthogonal to pass/fail.

### Added

- `goal` block on graphs: `required`, `description`, `supplied_by_trigger`.
- `run_graph(inputs=...)` seeds the blackboard at entry; omitting it reproduces prior
  behaviour byte-for-byte (the v1 trace lock still holds).
- `RunReport.goal_missing`, gating `passed`. Deliberately not written to `trace`, which
  means "nodes that executed".
- `agr goal <graph> "<text>"` and `agr eval --goal TEXT`.
- `goal_required` / `goal_description` on the MCP `search_graphs` result, so an agent
  learns what to bring before calling `get_graph` or `instantiate`.
- `/goal` slash command (`.claude/commands/goal.md`) — asks the user for a goal when the
  session has none, rather than inventing one.
- Four lints: required-but-unsupplied, consumed-but-undeclared, trigger-without-exemption,
  required-without-description.
- `registry.SPEC_VERSION` as the single source of truth for the registry's spec version.
- 🎯 **Requires a goal** line on the 31 affected cards.

### Changed

- `subgraphs.expand` no longer downgrades an expanded composite to `agr/v1.2` when the
  source uses a later feature. The stamp was always meant as a floor.
- Two version-completeness tests read `SPEC_VERSION` instead of a hardcoded version, so
  the test that catches an incomplete migration no longer has to be edited by every
  migration.

### Note on versioning

The registry skips `agr/v1.6`. That number arms a hard provenance lint in
`_lint_provenance` as a per-graph opt-in; migrating 83 graphs through it would have
armed an unrelated escalation and failed `clinical-protocol-lifecycle` on a
ground-truth field no binding here can obtain. See
[docs/agr-v1.7.md](docs/agr-v1.7.md#why-v17-and-not-v16).

## [0.8.0] — ability bindings

The seam shipped in M0 and no ability ever used it: `spec/agr-ability.schema.json`
has carried `binding: {kind, ref}` since the first commit, and 0 of 32 abilities
declared one. Every run in this repo'''s history sent a prompt and parsed JSON.

**The demonstration.** `docs-code-sync-audit` asserts
`all(e.exit_code == 0 for e in output.examples)`. Against `gpt-4o`:

| | tool calls | result | depth |
|---|---|---|---|
| tools off | 0 | **PASS** | `assert-live` |
| tools on | 20, all succeeded | **FAIL** | `assert-grounded` |

It only ever passed because the model fabricated `exit_code: 0`. With
`run_command` bound it fails, and the failure is the correct answer.

### Added
- `bindings.py`: `run_command`, `read_diff`, `web_search` bound to real
  implementations. Only a node'''s **declared** abilities are offered — never a
  general toolbox, which would discard the property that makes these graphs
  auditable.
- `ToolRunner`: an OpenAI tool-call loop over those bindings, bounded at 4 rounds.
- `assert-grounded`, above `assert-live`: the assert held *and* its values trace
  to a recorded tool call.
- `rep.tool_calls`, persisted into recordings so the grade survives replay.
  Grounding is a property of the run, not the node outputs — without this a
  replayed grounded run graded `assert-live`, the identical failure
  `assert-live` had before recordings existed.
- 21 tests, including the inverse property and the limit below.

### The permission model already existed
`abilities/*.yaml` has declared `risk: read|write|execute` since M0 — 18/6/8.
`read` binds freely; `write`/`execute` need `AGR_ALLOW_MUTATING=1`, the same gate
`agr eval --run-commands` uses. No second permission model was invented.

### What assert-grounded does NOT mean
The call was the right one. On the pilot run several of the 20 were theatre
(`echo '''Running test command 2'''`) and the node then described results in prose.
The trace proves something ran, not that the right thing ran. Stated because
`assert-fixture` went over-read for five versions.

`log_id`, `scanner_evidence` and `playbook_ref` need systems this repo has no
binding for. Those contracts stay unsatisfiable, truthfully.

## [0.7.0] — AGR v1.7 "one vocabulary"

Two structural fixes, found by reading the composite recordings after three prompt
patches failed to move anything.

**Fix A — `phase_frame` is key-preserving.** `output` is an accumulator, not a
slot: merging a phase's writes now unions `output` dicts key-wise, and a scalar
never displaces facts already gathered. Last-write-wins was silently undoing the
v1.6 reconcile node by node, which is why that fix measured as no change at all.

**Fix B — one vocabulary.** The registry asserts on `output.violations` while
nodes declare `outputs: [violations]` — two conventions for one contract, and the
declaration is the one the model is told. So a model returned the fact flat,
correctly, and the assert looking one level deeper missed it. `output.X` now
resolves to a flat blackboard key when `output` does not carry it. A key genuinely
inside `output` still wins, so a graph that nests properly is unaffected.

Resolved at evaluation, where the two vocabularies actually meet — rather than by
instructing a model out of the ambiguity, which failed three times.

### Results

| | before | after |
|---|---|---|
| graphs satisfied on every model | 42 | **48** |
| graphs satisfied by no model | 27 | **21** |
| composites satisfied by no model | 14 | **11** |

`gdpr-data-audit`, `invoice-reconciliation` and `procurement-lifecycle` pass —
the first composites ever to do so.

### The remaining 11 are not a harness problem

| failure kind | count |
|---|---|
| required key absent from the blackboard entirely | 11 |
| present but wrong type | 2 |
| evaluated false on real values | 4 |

None is a misplaced fact. **The composites are unproven at 7B–30B scale rather
than pending a fix**, and the README says so. The next useful measurement is a
frontier model, not another harness patch.

### Note
`test_no_child_node_in_the_recordings_produced_parent_keys` is marked
`xfail(strict=True)`: 3 of 35 child nodes still carry parent-contract keys, down
from 16 of 46. Strict, so it turns red the moment it starts passing and the marker
has to be removed — a tripwire rather than a loosened assertion.

## [0.6.1] — full-registry live coverage

No spec change. v1.5 closed the last structural gap, so the next finding had to
come from evidence — and it did.

**The v0.6.0 claim "contracts satisfied by no recorded model: 0" was read off a
slice, and the slice was the 25 *smallest* graphs.**

Recording all 83 — every composite and every human-gated graph, for the first
time — on `qwen3-coder:30b`:

| | 25-graph slice | all 83 |
|---|---|---|
| satisfied on every model | 13 | **42** |
| satisfied by **no** model | 0 | **27** |

And it is not spread evenly:

| shape | satisfied by no model |
|---|---|
| primitive | 11 of 65 |
| human-gated | 2 of 4 |
| **composite** | **14 of 14** |

**Every multi-phase composite fails on every model** — the graphs that were the
whole thesis of v1.1. The sample said 96%; the registry is 64%, and 0% on its most
ambitious graphs.

### Added
- `scripts/gen_breadth_report.py` → `docs/live-coverage.md`: what the evidence
  covers, by graph shape, so a pass rate can never again be read off a slice.
- `AGR_SAMPLES`: multiple recordings per graph+model cell. A second sample is a
  different observation, not a correction — one recording cannot distinguish a
  graph that passes from one that passed by luck. 🎲 marks the two cells where the
  same model both passed and failed.
- Replaying a human-gated graph honours the auto-approval its recording was made
  with, and stamps `gate_auto_approved` so the result is never mistaken for
  evidence the approval happened.

### Known limits
- One sample per cell for 130 of 133 cells; 🎲 only appears where there is more
  than one.
- Three local models, 7B–30B.

## [0.6.0] — AGR v1.5 "every node declares"

**v1.4'''s published diagnosis was wrong, and correcting it is this version.**

v1.4 shipped saying `ab-test-analysis` failed because "the contract has a joint
precondition no single node owns". Both keys were declared on **one** node. Nothing
joint about it. What the recordings showed — already checked in, unread — was the
two nodes *upstream* answering a question about their job instead of doing it:

    {"keys": ["recomputed_effect", "claimed_effect"]}
    {"keys_responsible": ["recomputed_effect"]}

They declared no outputs, so the prompt fell back to "return the keys this step is
responsible for" — a question about the node'''s job, which models answer literally,
naming keys instead of producing values. The judge downstream got an empty
blackboard and correctly emitted `null`.

    nodes (expanded):                      346
      declaring NO outputs:                103   (29%)
      of those, feeding a downstream node: 103   (all of them)

v1.4'''s lint asked whether *verification* had producers. Nothing asked whether a
node'''s **successors** have anything to consume.

### Results
`ab-test-analysis` — which failed every model for three versions — now passes on
`qwen3-coder:30b`. Contracts satisfied by no recorded model: 4 → 1 → **0**.

| Model | v1.3 | v1.5 |
|---|---|---|
| qwen3-coder:30b | 19/25 | **24/25** |
| hermes3:8b | 7/25 | **14/25** |
| qwen2.5-coder:7b | 11/25 | 11/25 |

The 7B model did not improve. Telling a node what it produces helps a model that
can follow the instruction; it does not make a small model capable of work it could
not do.

### Added
- `silent_nodes()` + lint: a node with a successor must declare an output. Error at
  `agr/v1.5`, advisory below. Terminals and `kind: subgraph` phases are exempt.
- `inputs` are checked against producers that can actually **reach** the consumer,
  as a fixed point (AGR graphs are deliberately cyclic). v1.1 checked set
  membership — "does this key exist anywhere" — which passes when the only producer
  runs strictly downstream.
- `joint_precondition_asserts()`: the 6 of 135 asserts genuinely spanning two
  producers get an advisory, not a `requires_all` field. Six cases do not justify
  new schema surface.
- Scoreboard reports node-declaration completeness alongside contract connection.

### Fixed
- 103 silent nodes declared, derived from the golden fixtures.
- 20 of them were one template copied 20 times: `mapper`/`worker`/`executor` — the
  nodes that do the work in map-reduce, parallel-swarm and PEV — declared nothing
  with a `{}` fixture to match.
- `LLMRunner` asks for concrete values and explicitly not for key names or plans.

### Guarantee
**No assert weakened** — 0 expressions changed, verified by parsing every graph at
HEAD against the working tree.

### The pattern, now named
Anything optional in the spec ends up unused, and anything unused ends up
load-bearing by accident. `outputs` was optional from v1.1; 29% of nodes skipped it
and the registry depended on them anyway. v1.5 adds no optional field.

**v1.5 is the first version where the registry has no known structural gap** — the
next finding will have to come from evidence, not from reading the spec.

## [0.5.0] — AGR v1.4 "connect the contracts"

No new machinery: one enum value, one lint, and a migration. The fields needed to
express this contract have existed since v1.1 and simply were not used.

**The gap.** A graph had two vocabularies with nothing checking they referred to
the same things — node `inputs`/`outputs` on one side, `verification[].assert` on
the other. **123 of 183 verification keys (67%) were produced by no declared node
output**, across 73 of 83 graphs. That is how four contracts stayed structurally
valid, passed the entire suite, and were satisfiable by no model: nothing ever
asked whether the nodes preceding a verifier produce what it asserts on.

**Result: contracts satisfied by no recorded model went 4 → 1.**

The acceptance criterion was "≥3 of 4 pass on qwen3-coder:30b" and only **2** do —
`differential-diagnosis-ensemble` is satisfied by the 7B model and not the 30B one.
**The criterion is missed as written**, and 4→1 does not erase that.

### Added
- `unconnected_keys()` and a lint: an **error** at `apiVersion: agr/v1.4`,
  advisory below it via `lint_advisories()` — never via `lint_graph()`.
- `asserted_keys()`: AST-based key extraction shared with `compose`. A regex
  version counted `f`, `v` and `for` as blackboard keys.
- `scripts/derive_outputs.py`: declarations derived from each graph'''s golden
  fixtures, which record per node exactly what it emits. 125 declarations, all 83
  graphs migrated to `agr/v1.4`.
- `LLMRunner` tells a node that assembles `output` to take values *from the
  blackboard* rather than return facts it never computed.
- Scoreboard reports contract connection alongside verification depth.

### Fixed
- **My own escape hatch hid the worst case.** `unconnected_keys` began with
  `if not produced: return set()` — excusing graphs that declare *nothing*, which
  is the maximal form of the gap, not an exemption from it.
  `code-review-pipeline` asserted on `output.verdict` while declaring no outputs
  and read as fully connected.
- **Advisories in the error channel bricked mutation.** Warnings were returned from
  `lint_graph`, which every caller treats as fatal, so `agr infuse` refused every
  graph with "rejected by gate: warn: ...".
- **The test suite reverted the migration on every run.** `test_mutate.py` restored
  its two mutated graphs with `git checkout` — from HEAD, not a snapshot — silently
  discarding uncommitted registry edits. Same two graphs whose stale profiles broke
  CI in v1.1.
- `kind: search` crashed on a non-numeric score instead of dropping the candidate.

### Guarantee
**No assert was weakened.** Verified by parsing every graph at HEAD and in the
working tree and comparing assert strings: **0 changed**. Only `outputs`
declarations were added.

### Open — the v1.5 item
`ab-test-analysis` asserts across two facts produced by *different* nodes; every
model supplied one and left the other null. Declaring both tells each node what it
owes; nothing states they must hold simultaneously for the assert to mean anything.

## [0.4.0] — AGR v1.3 "live"

Triggers, durability and enforced budgets — but the version'''s real work was
gathering enough evidence to know whether any of this registry survives contact
with a real model. It mostly does not, and now it says so.

**75 recordings: 25 graphs x 3 models, all checked in, failures included.**

| Model | Pass | Unparseable |
|---|---|---|
| qwen3-coder:30b | **19/25** | **0** |
| qwen2.5-coder:7b | 11/25 | 3 |
| hermes3:8b | 7/25 | 8 |

Of 27 recorded graphs: 7 satisfied on every model, 16 model-dependent, **4
satisfied by none**.

### Findings
- **A large share of "model failure" was harness brittleness — again.** `LLMRunner`
  extracted JSON with `text[text.index("{"):text.rindex("}")+1]`, which breaks on
  markdown fences, trailing commas, prose wrappers and Python `True`/`False`.
  Hardening it moved qwen2.5-coder 8→11 passes. Third version running where the
  headline problem was the harness misrepresenting the model.
- **Model choice dominates.** v1.2 shipped its entire live claim on one 7B model.
  On that evidence, 12 graphs looked like bad contracts a larger model satisfies
  perfectly. Only cross-model disagreement separates a weak model from an
  unsatisfiable contract.
- **4 contracts are satisfied by no model, and the attempted fix failed.**
  `output` is assembled by the terminal node from facts *upstream* nodes
  established; declaring the asserted keys on the terminal asks one node to report
  facts it never had. 0 of 12 re-recorded runs passed. The real gap — the I/O
  contract is per-node, the verification contract is graph-level, and nothing
  connects them — is recorded as the top v1.4 item rather than faked closed.

### Added
- `triggers` (schedule / webhook / signal) + **`agr triggers`** emitting crontab,
  GitHub Actions or a generic webhook filter. A signal GH Actions cannot express is
  flagged in the output, never silently dropped.
- `durability` + **`agr eval --resume-from`**. Resume is replay over v1.2 frames —
  no new state model. A resumed node routes through the same code path as a fresh
  one, and the test asserts trace *equality*.
- `budget` (`usd_max`, `steps_max`), **enforced**: checked before a node runs, not
  after it is recorded.
- Per-model recordings (`<case>@<model>.json`), per-model pass rates, and
  `models_disagree` / `fails_every_model` in `profile.json`.
- `docs/contract-findings.md`, generated from the recordings — a label that can be
  set by hand is a label that can be set to make a number look better.

### Removed
- `approval.timeout` and `retries.backoff`, which had been accepted-and-ignored
  since v1.1. v1.3'''s rule — no field without an executing consumer in the same
  version — applied retroactively.

### Known limits (stated, not buried)
- Recordings cover 27 of 83 graphs; composites and human-gated graphs have none.
- Each cell is one sample; a ✅ may have passed by luck.
- Three local models, 7B–30B. Nothing is claimed about frontier models.

## [0.3.0] — AGR v1.2 "depth"

Graphs that search or learn rather than follow a fixed path — and, more
importantly, the first real evidence about whether any of them work.

**The finding.** v1.1 shipped verification *depth grading* and reported honestly
that 73 of 74 graphs sat at `assert-fixture`. v1.2 made `assert-live` reachable and
recorded five runs against a local qwen2.5-coder:7b. **All five failed** — every one
raising `NameError: name '''output''' is not defined` on the exact key its contract
asserts. The cause was not model quality: `LLMRunner`'''s prompt had asked for "your
output keys" since v1.0 without ever saying which, and v1.1'''s declared `outputs`
contracts existed only on composites, so all 74 primitives gave a model nothing to
aim at. After fixing both, 4 of 5 pass. The fifth is checked in still failing.

A registry reporting 74/74 at 100% was, on first contact with a real model, 0/5.

### Added
- **Frames.** Every node execution records what it wrote. Phase-scoped
  verification, real fan-out and search results are all projections over them.
- **`fan_out`** — one node, N executions over a blackboard list, each with its own
  frame. Truncation past `max` is logged, never silent.
- **`aggregate`** — majority / median / union / best, reducing before the node
  runs. `majority` returns None on a tie rather than breaking it silently.
- **`kind: search`** — bounded beam search (branch x depth, beam prune),
  reporting whether a run measurably improved. Beam search, not MCTS, and the
  docs say so.
- **Phase-scoped verification** — expansion now merges a child'''s verification
  tagged with its phase and evaluates it against that phase'''s frame. Closes the
  v1.1 deferral: a composite inherits its children'''s contracts.
- **`memory`** (`scope: run|graph`) and **enforced `state.schema`** — v1.1 accepted
  the latter and never read it, deferring until it had a consumer; `memory` is it.
- **`ReplayRunner`** — checked-in real-model recordings make `assert-live`
  reachable in CI. Reported in a separate `measured_live` block so a contract a
  real model cannot satisfy cannot hide inside an average. Scoreboard shows model
  and recording date, flagging anything over 90 days.
- **`LLMRunner.bind(doc)`** — the live runner now states the declared outputs,
  termination contract and downstream asserts it requires.
- 9 v1.2 graphs across 6 new motifs (tree-search, ensemble-quorum, tournament,
  reflexion, red-team-blue-team, blackboard). Registry: 74 -> **83 graphs**,
  13 -> **19 motifs**, 100 -> **135 tests**, catalog 123 -> **131 entries**.

### Fixed
- **17 graphs claimed parallelism they did not have.** `parallel_group` was a
  decorative string: a map-reduce graph executed its `map` node exactly once.
  Those are real `fan_out` now. The label survives only where it marks two
  *distinct* sibling nodes, and a test fails if any group has fewer than 2 members.
- Every graph whose asserts read `output.*` now declares it as an output, so a
  live runner has a target.
- `make check` mirrors the CI gate (regenerate, then diff) — the v1.1 release
  passed local pytest and still failed CI on stale generated docs.

### Known limits (stated, not buried)
- Live recordings are one model, one case per graph: enough to prove the mechanism
  and surface the contract bug, not enough to claim anything general.
- Search graphs are tested against synthetic gradients, not a real scorer.
- `approval.timeout` and `retries.backoff` remain recorded but unenforced.

## [0.2.0] — AGR v1.1 "composites"

Depth instead of length. v1 gave 52 graphs averaging 3.2 nodes and a 4-node ceiling;
the blocker was never content, it was that the spec could not express a multi-phase
workflow. v1.1 adds the primitives that make composition real, then builds 22
composites on them.

**Every v1 graph validates and executes unchanged.** The scheduler was replaced
wholesale against `tests/fixtures/v1_trace_lock.json`, which proves all 106
pre-existing eval cases produce byte-identical traces.

### Added — AGR v1.1 spec (additive; `apiVersion` accepts `agr/v1` and `agr/v1.1`)
- `kind: subgraph` + `ref`: a phase that *is* another registry graph, inlined at
  load with id prefixing, boundary rewiring, contract transfer, depth cap and
  cycle detection.
- `join`: `any` (default, = v1 behaviour) | `all` | `quorum(n)`, with dead-branch
  *settlement* so a router-skipped predecessor cannot hang an `all` join.
- `kind: human` made executable: an `approval.contract` that blocks every outgoing
  flow edge until satisfied. `LLMRunner` raises `HumanGateRequired` rather than
  sign its own gate; `--auto-approve` is CI-only and stamps the profile.
- `edges[].kind`: `flow` | `error` | `compensate`, plus `on_error` sugar and
  per-node `retries`.
- Declared `inputs`/`outputs` I/O contracts, and `state.inputs`.
- `verification[].describe` for prose; `assert` must now `ast.parse` (lint error).
- Verification **depth grading** in `profile.json` and the README scoreboard:
  `describe-only` < `assert-fixture` < `assert-live` < `command`.
- Opt-in verification-command execution: `agr eval --run-commands`.
- `agr compose --mode subgraph`: emit a parent that references both graphs
  instead of splicing them; declared contracts preferred over the v1 heuristic,
  with `contract_basis()` reporting which check ran.
- 22 composite graphs across five new motifs (`lifecycle`, `human-gate`,
  `supervisor-hierarchy`, `saga`, `escalation-ladder`), incl.
  `feature-delivery-lifecycle` — research → plan → implement → test → audit → fix
  → docs → release, 10 authored nodes executing as 17.
- 14 new specialities, 12 new abilities. Registry: 52 → **74 graphs**,
  106 → **130 eval cases**, 52 → **100 tests**, catalog 114 → **123 entries**.

### Fixed
- **Entry-node definition was inconsistent between harness and linter.** A graph
  whose retry edge pointed back at its first node had no entry at all and executed
  zero steps while `agr validate` reported it clean. Both now call one shared
  `entry_nodes()`: no incoming *forward* edge of any kind.
- **`attempts` was read by 48 edge guards and written by nothing.** `edge_true`
  swallowed the `NameError` and returned False, so every bounded retry loop in the
  registry silently failed closed. Masked because golden fixtures supplied the
  value the runtime owed. The harness now publishes the per-node visit count.
- **`agr adapt` silently dropped subgraph children**, emitting 10 nodes for a graph
  that executes 17 — each phase became one `NotImplementedError` stub. All three
  emitters expand first; a new parity test asserts compiled topology covers the
  executed trace for every graph and every target.
- `gen_traces.py` crashed on expanded node ids (same class as the above).
- `verification[].command` entries are no longer merely counted when execution is
  requested — they were previously always skipped, so "executable verification"
  was not a capability the harness had.

### Known limitations (stated, not hidden)
- 73 of 74 graphs verify at `assert-fixture` depth: the assert held against a mock
  written alongside the graph. This proves the topology routes values through, not
  that a claim was earned. Deepening it is the v1.2 problem.
- Child `verification` is not merged into a parent on expansion — correct
  evaluation needs phase-scoped blackboard snapshots (v1.2). A lint requires
  composites to declare their own verification instead.
- `state.schema` is still an unread string; `approval.timeout` and
  `retries.backoff` are recorded but not enforced (the harness has no clock).
- `agr compose --mode inline` still uses the v1 identifier heuristic for the 52
  graphs that declare no I/O contract. The verdict reports `[heuristic]` so its
  strength is never implied.

## [0.1.0] — unreleased

### Added
- AGR v1 spec: JSON Schemas for graph, speciality, ability (15-domain taxonomy).
- Validator: schema conformance + MAST structural lint (dangling edges, unreachable
  nodes, unconditional back-edges, verifier-without-verification, unresolvable
  specialities/abilities).
- `agr` CLI: `list`, `search`, `validate`, `show`, `mermaid`, `profile`.
- 52 graphs across 15 domains (3 handcrafted, 49 pattern-template instantiations
  from the top-50 use cases).
- Use-case catalog: 112 audited entries; executable audit wired into pytest.
- 20 specialities, 20 abilities (risk-leveled, MCP-bindable).
- CI gate (GitHub Actions): validate + audit + tests (all extras).
- **M1** eval harness: graph interpreter (routers, joins, bounded loops, contract
  asserts), MockRunner (golden fixtures) + LLMRunner (any OpenAI-compatible endpoint),
  `agr eval` writing `profile.json` with runner provenance; golden cases + passing
  provisional profiles for the 3 handcrafted graphs.
- **M2** mutation layer: `agr infuse` (gate-checked ability injection with
  `lineage.yaml` provenance) and `agr optimize` (deterministic hill-climb:
  duplicate-edge dedupe, sibling parallelization, measurement-driven max_steps
  tightening; reverts any operator that breaks golden cases).
- **M3**: `agr adapt` LangGraph codegen (self-contained source, structure compiled,
  behavior left as explicit NotImplementedError bindings) and `agr mcp` MCP server
  (`search_graphs`, `get_graph`, `instantiate`, `infuse_ability`; compatible with
  mcp SDK 1.x and 2.x).
