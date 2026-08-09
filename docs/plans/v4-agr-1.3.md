# v4 — "Live graphs" (AGR v1.3)

Stage 1 of 7. Implements the v4 slice of
[`graph-expansion-v2-v4.md`](graph-expansion-v2-v4.md).

**Goal:** graphs stop being functions and become services — triggered by events,
durable across restarts, bounded by real budgets.

---

## 1. What v3 actually taught, and what it changes here

v3's headline was not a feature. It was that the first five real-model runs
**failed 5/5** because the harness never told the model what contract it owed.
Two lessons carry into v4, and they outrank the feature list:

**Lesson 1 — a declared capability is worth nothing until something consumes it.**
`state.schema` was accepted-and-ignored for two versions. `memory` validated and
did nothing until v3 stage 5. `parallel_group` labelled parallelism that did not
exist across 17 graphs. Every one of these passed schema, lint and tests.

*So v4 ships no field without an executing consumer in the same version.* Any
feature that cannot be consumed is cut, not deferred with a note.

**Lesson 2 — the dangerous failures are the ones that pass green.**
`attempts` unwritten, adapters dropping subgraph children, `parallel_group`,
`LLMRunner` never reading contracts: all passed a full suite. Each was invisible
because the *test fixtures supplied what the runtime owed*.

*So every v4 criterion must be falsifiable by something other than a fixture.*

**This is why v4's headline is not `triggers`.** It is closing the evidence gap
v3 opened: 5 recordings on one model is not evidence about a registry of 83.

---

## 2. Design decisions

### D1 — Evidence breadth before new surface

v3 proved recordings work. v4's first job is **breadth**: ≥25 graphs recorded
across **≥3 models** of different sizes. This is the only way to distinguish
"this graph's contract is unsatisfiable" from "that one 7B model was weak".

Expected outcome, stated in advance so it cannot be rationalised later: **a
meaningful fraction of the registry will fail.** Every failure is checked in. A
graph whose contract no model satisfies is a graph with a bad contract, and the
scoreboard will name it.

*Rejected:* shipping `triggers` first. A watch-loop firing a graph that no model
can satisfy is an automated way to be wrong on a schedule.

### D2 — `triggers` declare, the runtime does not schedule

```yaml
triggers:
  - {on: schedule, cron: "17 * * * *"}
  - {on: webhook, source: github, event: pull_request}
  - {on: signal, expr: "error_budget_burn > 2.0"}
```

AGR describes *when a graph wants to run*; it does not become a scheduler. `agr
triggers <name>` emits the host-native form (cron entry, GitHub Actions workflow,
webhook filter). Consumer: the emitter plus a test that a declared trigger
round-trips.

*Rejected:* a built-in daemon. That is a product, not a registry, and it would be
another declared-but-unconsumed surface within a version.

### D3 — Durability as replayable frames, not a database

v1.2 already records every node execution as a frame. Checkpointing is therefore
**append frames to a journal; resume by replaying them and skipping completed
nodes.** No new state model, no new storage engine.

```yaml
durability: {checkpoint: every_node, resume: true}
```

Consumer: `agr eval --resume-from <journal>` plus a test that kills a run
mid-graph and resumes to the same terminal state.

### D4 — Budgets enforced, because unenforced limits are the v3 anti-pattern

```yaml
budget: {usd_max: 5.00, steps_max: 200}
```

`run_graph` tracks estimated spend per node and **halts** when exceeded, with
`rep.budget_exhausted` set. Enforced or absent — `approval.timeout` and
`retries.backoff` have been "recorded but not enforced" since v1.1 and this plan
either fixes them or deletes them from the schema.

### D5 — Federated supervisor reuses subgraphs, adds only a work-list

`fan_out` over targets + `kind: subgraph` per target already expresses "run this
migration across N repos". v4 adds `target` binding so a subgraph phase can be
parameterised per shard. No new motif machinery.

---

## 3. Work breakdown

| # | Change | Est. |
|---|---|---|
| 1 | Record ≥25 graphs × ≥3 models; scoreboard shows per-model results and disagreement | 10h |
| 2 | Triage what the recordings expose; fix or explicitly mark bad contracts | 8h |
| 3 | `triggers` schema + `agr triggers` emitter (cron / GH Actions / webhook) | 6h |
| 4 | Journal + `--resume-from`, built on frames | 8h |
| 5 | `budget` enforcement; resolve `approval.timeout` / `retries.backoff` (enforce or delete) | 5h |
| 6 | ~12 v1.3 graphs (watch-loop, federated-supervisor, market, simulation) | 8h |
| 7 | Tests + docs | 8h |

**≈53h.** Item 1 gates 2, and 2 may reshape 6.

---

## 4. Acceptance criteria

Each is falsifiable by something other than a fixture — the v3 lesson.

| # | Criterion | Falsified by |
|---|---|---|
| C1 | ≥25 graphs recorded across ≥3 models | count of `evals/*/live/*.json` |
| C2 | The scoreboard reports per-model pass rate **and disagreement between models** | a model-disagreement column that is never non-zero |
| C3 | Every graph failing on **all** models is either fixed or labelled `contract-unsatisfiable` | a failing graph with no label |
| C4 | `agr triggers` emits a valid host-native artifact for all 3 trigger kinds | round-trip test |
| C5 | A run killed mid-graph resumes to the identical terminal state | kill-and-resume test asserting trace equality |
| C6 | A budget cap **halts** a run; `rep.budget_exhausted` is set | test with a cap of 0 |
| C7 | `approval.timeout` and `retries.backoff` are enforced **or removed from the schema** | grep: no accepted-and-ignored fields remain |
| C8 | v1/v1.1/v1.2 trace locks hold; tests green; `make check` clean | CI |

**C3 is the one that matters.** C1 gathers evidence and C2 displays it, but C3 is
the commitment to *act* on it — including admitting that some graphs in this
registry ask for something no model delivers.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Recording 25 × 3 is slow on local models | run in background, smallest-first; a partial sweep is still evidence, and the count is reported honestly |
| Mass failures tempt loosening contracts to go green | contracts may only be *corrected*, never weakened, without saying so in the audit; C3 requires a label, not a pass |
| `triggers` becomes another unconsumed field | D2 ships the emitter in the same version, or the field is cut |
| Resume diverges subtly from a fresh run | C5 asserts trace equality, not "looks similar" |
| v4 balloons past what one version should hold | items 3–6 are droppable; items 1–2 are not |

---

**Next stage:** v4.2 — implement, starting with the recording sweep, because what
it exposes may change what is worth building.
