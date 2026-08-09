# Changelog

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
