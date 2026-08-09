# Changelog

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
