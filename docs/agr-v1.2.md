> **Superseded by [AGR v1.8](agr-v1.8.md).** This page describes an earlier version and is kept for the record; the current spec is agr-v1.8.md.

# AGR v1.2 — depth

Additive over v1.1. Every v1 and v1.1 graph validates and executes unchanged.

The one idea underneath everything here: **the blackboard gained a history.**
v1.1's three biggest debts — fixture-deep verification, child contracts dropped on
expansion, and `parallel_group` labelling parallelism that did not exist — were all
the same missing capability.

## Frames

Every node execution appends `{node, visit, out}` to `rep.frames` — what that
execution *wrote*, not a copy of the whole board. Cheap enough to keep for every
step, and the substrate for everything below.

- `rep.frames_for(node_id)` — one entry per visit, so a retry loop is observable.
- `rep.phase_frame(phase)` — every write inside a subgraph phase, merged in order.
  Merged, not last-only: run standalone, a child ends with an *accumulated* board
  and its asserts were written against that.

## `fan_out` — one node, N executions

```yaml
- id: map
  fan_out: {over: shards, max: 20, on_partial: continue}   # continue | fail
```

Runs once per element of `bb["shards"]`, each with `shard`, `shard_index` and
`shard_count`, each leaving its own frame. Declared outputs become **lists**
downstream — which is why this is opt-in and not inferred from `parallel_group`.

Truncation is **never silent**: exceeding `max` appends to `rep.truncations` saying
exactly how many items were not processed. A truncated fan-out reporting full
coverage is the quiet lie this spec refuses.

`parallel_group` survives only where it marks two *distinct* sibling nodes
(`debate`, `code-review-pipeline`'s two reviewers). It is a scheduling annotation
there, not a cardinality claim. 17 graphs that used it as a stand-in for fan-out
were migrated.

## `aggregate` — reduce before the node runs

```yaml
- id: vote
  aggregate: {op: majority, over: rubric_score}   # majority | median | union | best
```

A node property rather than a new node kind, so it reuses the join machinery v1.1
already ships. **`majority` returns `None` on a tie** — a tie is a signal, not
noise to be broken silently.

## `kind: search` — bounded beam search

```yaml
- id: explore
  kind: search
  search: {branch: 4, depth: 3, score: "bench_ms", objective: min, prune: "beam(2)"}
```

**This is beam search, not MCTS.** No rollout policy, no learned value function —
both need a real environment, and faking one produces exactly the fixture-deep
evidence v1.2 exists to escape. Bounded by `branch × depth`, deterministic,
step-capped. `rep.searches` records each round's best score and whether the run
*measurably improved*; an unscoreable candidate is dropped, not crashed on.

## Phase-scoped verification

```yaml
verification:
  - phase: audit                       # evaluate against that phase's frame
    assert: "output.verdict == 'approve'"
```

v1.1 dropped a child's verification on expansion because its asserts only held at
the instant its terminal ran; against a board a later phase had overwritten they
failed for unrelated reasons. Frames make the correct scope available, so
expansion now **merges** child verification, tagged with the phase id. A composite
inherits its children's contracts — and must satisfy them.

## `memory` and `state.schema`

```yaml
memory: {scope: graph}                 # run | graph
state:  {schema: state/lessons.schema.json}
```

`scope: run` keeps `lessons` on the report; `scope: graph` appends them to
`graphs/<...>/memory.jsonl` so the next run reads what the last one learned. A
reflexion graph that cannot carry a lesson past one run is a retry loop with extra
vocabulary.

`state.schema` is now **loaded and enforced** — v1.1 accepted it as a string and
never read it, deferring "until it has a consumer". `memory` is that consumer: an
accumulator without a pinned shape becomes untyped sludge.

## `ReplayRunner` — real evidence in CI

Recordings live at `evals/<graph>/live/<case>.json`, stamped with model and date.
A graph with one grades `assert-live` instead of `assert-fixture`, with no network
call. Record with `scripts/record_live.py`.

Live results are reported in their **own** `measured_live` block, never blended
into the headline pass rate: a contract a real model cannot satisfy must not be
able to hide inside an average.

A recording whose asserts fail is kept, not deleted. `kb-article-generator` is
checked in failing because the model returned `output: true` where the contract
needs an object — that is the finding, and removing it would restore the
comfortable fiction the fixture depth already gives.

## `LLMRunner` states the contract

`LLMRunner.bind(doc)` is called before execution and puts the node's declared
`outputs`, the graph's termination contract, and the downstream asserts into the
prompt. Without it the prompt asked for "your output keys" and never said which —
which is why the first five real recordings failed 5/5.

## Not in v1.2

| | |
|---|---|
| `triggers`, durability, budgets | v1.3 — graphs are still functions, not services |
| org-scoped memory | needs durability |
| `approval.timeout`, `retries.backoff` | still recorded, not enforced (no clock) |
| live evidence breadth | one model, one case per graph — mechanism proven, not generality |
