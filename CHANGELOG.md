# Changelog

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
