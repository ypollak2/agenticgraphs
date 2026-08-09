# v3 — "Deep graphs" (AGR v1.2)

Stage 1 of 7. Implements the v3 slice of
[`graph-expansion-v2-v4.md`](graph-expansion-v2-v4.md), plus the two items v2
explicitly deferred here.

**Goal:** graphs that *search* and *learn* instead of executing a fixed path — and
verification that means something.

**The debt v2 handed over, in priority order:**

1. **73 of 74 graphs verify at `assert-fixture` depth.** The scoreboard says so
   honestly now, but honesty is not a fix. This is the registry's largest weakness.
2. **Child verification is dropped on subgraph expansion**, because a child's
   asserts only hold at the instant its terminal ran. Needs phase snapshots.
3. **`parallel_group` is a label, not a fan-out.** A map-reduce graph executes its
   `map` node exactly once. 16 graphs claim parallelism they do not have.

All three are the same missing capability: **the blackboard has no history.** Fix
that and phase-scoped verification, real fan-out, and reflexion memory all follow.

---

## 1. Design decisions

### D1 — Snapshots are the foundation, not `fan_out`

The blackboard is a single flat dict that every node overwrites. Introduce a
**frame** per node execution: `(node_id, visit, inputs_seen, outputs_written)`,
appended to `rep.frames`. Cheap (a dict copy of what a node wrote, not the whole
board) and unlocks all three debts:

| Debt | How frames fix it |
|---|---|
| phase verification | evaluate a child's asserts against the frame at its terminal |
| fan-out | each shard is a frame of the same node at a different index |
| reflexion memory | a lesson is a projection over prior frames |

*Rejected:* implementing `fan_out` first. Without frames, N shards would collapse
into one blackboard write and the last shard would win silently — the same class
of bug as `attempts`.

### D2 — `fan_out` iterates a blackboard key, and partial failure is explicit

```yaml
- id: map
  fan_out: {over: shards, max: 40, on_partial: continue}   # continue | fail | quorum(n)
  outputs: [shard_result]
```

The node runs once per element of `bb["shards"]` (capped at `max`, and the cap is
**logged, never silent** — a truncated fan-out that reports full coverage is a lie
the v2 audit specifically warned about). Each run gets `shard` and `shard_index`
on its frame. Downstream, `shard_result` is a **list**, not a scalar.

That last point is a breaking change for any graph that fans out, so `fan_out` is
opt-in and the 16 existing `parallel_group` graphs are migrated deliberately, not
automatically.

### D3 — `aggregate` is a node property, not a new node kind

```yaml
- id: vote
  join: quorum(3)
  aggregate: {op: majority, over: shard_result, tie_break: judge}  # majority | median | union | best
```

Reuses the join machinery already shipped in v1.1 rather than inventing a parallel
concept. `aggregate` runs *before* the node's runner, so the node sees a reduced
value.

### D4 — `kind: search` is a bounded loop with a score, not an engine

```yaml
- id: explore
  kind: search
  search: {branch: 4, depth: 3, score: "output.bench_ms", objective: min, prune: "beam(2)"}
```

Expands at run time into `branch × depth` frames with beam pruning — deterministic,
inspectable, and step-capped like everything else. No MCTS rollout policy, no
learned value function: those need a real environment, and inventing one would
produce exactly the fixture-deep verification v3 exists to escape.

*This closes the README's long-standing "AFlow-style MCTS search remains open"
item in the honest, bounded form — and says plainly that it is beam search, not MCTS.*

### D5 — `memory` is scoped and explicit

```yaml
memory:
  scope: run          # run | graph  (org-scope is v1.3, it needs durability)
  schema: ./state/lessons.schema.json
```

`scope: run` keeps lessons in `rep`; `scope: graph` persists to
`graphs/<...>/memory.jsonl` — which finally gives `state.schema` a consumer, the
reason v2 deferred it.

### D6 — Phase-scoped verification, closing the v2 deferral

```yaml
verification:
  - phase: audit                              # NEW: evaluate against that phase's terminal frame
    assert: "output.verdict == 'approve'"
```

On expansion, a child's `verification` entries are now merged into the parent
**tagged with the phase id**, and evaluated against that phase's terminal frame
instead of the final blackboard. The v1.1 lint requiring composites to declare
their own verification stays — belt and braces.

### D7 — `assert-live` becomes reachable in CI

Depth grading exists but nothing ever produces `assert-live`. Add a
`ReplayRunner`: recorded real-model outputs, checked into `evals/<name>/live/`.
Graphs with a recording grade `assert-live` and the number becomes real without
a network call in CI.

*This is the single highest-value item in v3* — it converts the honesty of the
depth column into actual depth for the graphs that matter most.

---

## 2. Schema diff

```jsonc
"nodes[]": {
  "kind":      { "enum": [..., "search"] },
  "fan_out":   { "over": "string", "max": "integer 1..100",
                 "on_partial": "enum[continue,fail,quorum(n)]" },
  "aggregate": { "op": "enum[majority,median,union,best]", "over": "string",
                 "tie_break": "string" },
  "search":    { "branch": "int 2..8", "depth": "int 1..4", "score": "expr",
                 "objective": "enum[min,max]", "prune": "beam(n)|none" }
},
"memory":         { "scope": "enum[run,graph]", "schema": "path" },
"verification[]": { "phase": "string (node id of a subgraph phase)" }
```

Conditional: `kind: search` ⇒ `search` required · `fan_out` ⇒ `over` must be
produced upstream (lint) · `aggregate.over` likewise · `verification[].phase` must
name a `kind: subgraph` node.

---

## 3. Work breakdown

| # | File | Change | Est. |
|---|---|---|---|
| 1 | `harness.py` | frames (`RunReport.frames`), per-frame output capture | 4h |
| 2 | `harness.py` | `fan_out` execution, `on_partial`, truncation logging | 6h |
| 3 | `harness.py` | `aggregate` reduction before runner | 3h |
| 4 | `harness.py` | `kind: search` — branch/score/prune loop | 6h |
| 5 | `harness.py` + `subgraphs.py` | phase-tagged verification against terminal frames (D6) | 4h |
| 6 | `harness.py` | `ReplayRunner` + `memory` scopes | 4h |
| 7 | `spec/`, `validate.py` | schema + 6 new lints | 5h |
| 8 | `graphs/**` | ~20 v1.2 graphs (§4) + migrate the 16 `parallel_group` graphs to real `fan_out` | 12h |
| 9 | `evals/**`, `tests/` | golden cases, live recordings for ≥5 graphs, test suite | 10h |

**≈54h.** Critical path is 1 → 2 → 5. Item 1 gates everything.

---

## 4. The ~20 graphs

Six new motifs: `reflexion`, `tree-search`, `tournament`, `ensemble-quorum`,
`red-team-blue-team`, `blackboard`.

| Graph | Domain | Motif |
|---|---|---|
| `architecture-decision-tournament` | software-engineering | tournament |
| `benchmark-driven-optimization-search` | software-engineering | tree-search |
| `prompt-graph-optimization` | research-knowledge | tree-search (the AFlow item) |
| `flaky-test-reflexion` | software-engineering | reflexion |
| `red-team-blue-team-hardening` | security | red-team-blue-team |
| `exploit-repro-and-patch` | security | reflexion |
| `forensic-investigation-blackboard` | security | blackboard |
| `self-healing-ci` | devops-sre | reflexion |
| `capacity-forecast-search` | devops-sre | tree-search |
| `differential-diagnosis-ensemble` | healthcare-science | ensemble-quorum |
| `portfolio-strategy-tournament` | finance | tournament |
| `fraud-pattern-triage` | finance | ensemble-quorum |
| `curriculum-designer` | education | reflexion |
| `tutoring-router` | education | escalation-ladder + reflexion |
| `ad-variant-tournament` | content-marketing | tournament |
| `case-law-research` | legal-compliance | blackboard |
| `survey-design-critic` | research-knowledge | ensemble-quorum |
| `systematic-meta-analysis` | research-knowledge | fan-out + quorum |
| `churn-signal-analysis` | customer-support-sales | ensemble-quorum |
| `sales-call-scorer` | customer-support-sales | ensemble-quorum |

All 20 already exist as orphaned catalog entries — no new catalog invention needed.

Post-v3: **94 graphs**, 19 motifs, catalog coverage 94/123.

---

## 5. Acceptance criteria

Written to be falsifiable, and with v2's lesson applied: **no criterion that can
only be met by authoring more YAML.**

| # | Criterion | Measured by |
|---|---|---|
| B1 | `fan_out` executes n>1 shards; trace shows n frames for one node | test |
| B2 | A truncated fan-out (`max` < len) **logs** what it dropped | test asserting the warning |
| B3 | The 16 `parallel_group` graphs either use real `fan_out` or drop the label | sweep |
| B4 | Phase-scoped verification evaluates against the phase's frame, closing the v2 deferral | test: a child assert that passes in-phase and would fail against the final board |
| B5 | ≥5 graphs grade `assert-live` via recorded runs | scoreboard |
| B6 | ≥3 graphs measurably improve a score across iterations | test on `search` |
| B7 | `state.schema` is loaded and enforced (v2's deferral, now with a consumer) | test |
| B8 | v1 + v1.1 trace locks both hold; `pytest` green; lint clean | CI |

**B5 is the criterion that matters.** B1–B4 are mechanism; B5 is whether the
registry's evidence got deeper. If B5 slips, v3 has not delivered its point.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Frames balloon memory on wide fan-outs | store only per-node writes, not board copies; cap frames at `max_steps × fan_out.max` |
| `fan_out` breaks the 16 `parallel_group` graphs (scalar → list) | opt-in; migrate deliberately with a per-graph trace lock, as v2 did |
| `kind: search` becomes an unfalsifiable "it explores" claim | B6 requires a *measured* score improvement, not the presence of branches |
| Live recordings rot as models change | stamp each recording with model + date; scoreboard shows the age |
| Same v2 failure: 20 graphs stamped from 6 new templates | every new motif gets ≥1 hand-authored graph; stage-4 audit checks motif diversity, not count |

---

**Next stage:** v3.2 — implement, critical path items 1 → 2 → 5.
