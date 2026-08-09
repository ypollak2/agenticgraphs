# v3 audit — AGR v1.2 against its own plan

Stage 4 of 7. Every number measured against the registry at the end of stage 3.

**Verdict: 6 of 8 criteria met. Two missed. But the headline finding is not a
criterion at all — it is what happened when real models were pointed at the
registry for the first time.**

---

## 1. The finding that matters

v1.1 shipped verification *depth grading* and reported honestly that 73 of 74
graphs sat at `assert-fixture`. v1.2 made `assert-live` reachable and recorded
five real runs against a local `qwen2.5-coder:7b`.

**All five failed on the first attempt.** Not marginally — every single one raised
`NameError: name 'output' is not defined` or an `AttributeError` on the very key
its contract asserts.

The cause was not model quality. It was the harness:

```python
# LLMRunner.run, as shipped in v1.0 and untouched through v1.1
"Reply with ONLY a JSON object of your output keys."
```

The prompt asked for "your output keys" and never said **which**. v1.1 had
introduced declared `outputs` contracts per node — and the live runner never read
them. A real model returned plausible JSON with entirely different key names, and
every contract failed.

Two fixes followed, both of which are the actual v1.2 deliverable:

1. `LLMRunner.bind(doc)` — the runner now states the node's declared `outputs`,
   the graph's termination contract, and the downstream asserts that must hold.
2. Declared `outputs` were only ever applied to composites. All 74 primitives had
   **no declared contract at all**, so a live model had nothing to aim at. Every
   graph whose asserts read `output.*` now declares it.

After both: **4 of 5 pass at `assert-live`.** The fifth (`kb-article-generator`)
still fails, honestly, because the model returned `output: true` — a boolean where
the contract needs an object. That recording is kept, not deleted.

This is the whole argument for depth grading. A registry reporting "74/74 at 100%"
was, on first contact with a real model, **0/5**.

---

## 2. Acceptance criteria

| # | Criterion | Target | Actual | |
|---|---|---|---|---|
| B1 | `fan_out` executes n>1 shards, trace shows n frames | works | 4 graphs, tested | ✅ |
| B2 | truncated fan-out logs what it dropped | works | tested | ✅ |
| B3 | the 16 `parallel_group` graphs use real `fan_out` or drop the label | all | **19 still label-only** | ❌ |
| B4 | phase-scoped verification against the phase frame | works | 14 graphs | ✅ |
| B5 | ≥5 graphs grade `assert-live` via recordings | ≥5 | 5 (4 passing) | ✅ |
| B6 | ≥3 graphs measurably improve a score across iterations | ≥3 | 3 search graphs, improvement asserted | ✅ |
| B7 | `state.schema` loaded and enforced | yes | **not implemented** | ❌ |
| B8 | trace locks hold, pytest green, lint clean | yes | 128 tests, 0 lint errors | ✅ |

Registry: **83 graphs**, 19 motifs, catalog 131 entries, 128 tests.

---

## 3. Findings

### F1 — B3 missed: 19 graphs still label parallelism they do not have (blocking)

`parallel_group` remains a decorative string on 19 graphs while only 4 use real
`fan_out`. A `map-reduce` graph still executes its `map` node exactly once.

This is the same class of dishonesty as the fixture-deep pass rate: the artifact
claims a property it does not have. It must be either made true or removed.

*Complication that makes it real work:* `fan_out` changes a declared output from a
scalar to a **list** downstream, so every migrated graph needs its asserts and
fixtures reworked. That is why it was not done wholesale in stage 2, and it is not
a reason to leave the label lying.

*Note on scope:* the `debate` motif's `parallel_group` is not fan-out at all — it
marks two *distinct* sibling nodes, not N copies of one. There the label is
meaningful and only the execution is sequential. Those must be handled separately
rather than force-fitted.

### F2 — B7 missed: `state.schema` still unread (blocking)

Deferred from v1.1 on the explicit grounds that it had no consumer until `memory`
existed. `memory` now exists (2 graphs use `scope: graph`) — so the justification
expired and the feature still was not built. Deferring twice for the same reason
is how a spec accumulates decoration.

### F3 — `memory` is declared but does nothing

`memory: {scope: graph}` validates, lints, and is completely inert: nothing writes
`lessons`, and the two reflexion graphs get their lessons from fixtures. The motif
is real; its persistence is not. Currently indistinguishable from decoration.

### F4 — recordings have no freshness signal in the scoreboard

Each recording stamps its model and date, and the plan said the scoreboard would
show the age. It shows the model only. A recording is evidence with a shelf life;
without the date a reader cannot tell a fresh result from a year-old one.

### F5 — only one model, one case per graph

Five recordings, all `qwen2.5-coder:7b`, all the first case only. That is enough to
prove the mechanism and to surface the contract bug — it is not enough to claim
anything about how the registry behaves under models generally. Stated so the
number is not over-read.

### F6 — the search motif is honest but shallow

3 graphs use `kind: search`, and `improved` is asserted on synthetic gradients in
tests. No search graph has been run against a real scorer. The README claim should
say "bounded beam search, mechanism tested" and nothing stronger.

---

## 4. Stage 5 work list

1. **F1/B3** — migrate map-reduce and parallel-swarm graphs to real `fan_out`
   (asserts and fixtures reworked); strip `parallel_group` where it was decorative;
   keep and document it only where it marks distinct siblings.
2. **F2/B7** — implement `state.schema` loading and blackboard validation.
3. **F3** — make `memory` write real lessons, or remove it from the spec. A
   declared feature that does nothing is worse than an absent one.
4. **F4** — scoreboard shows recording date and flags recordings older than 90 days.
5. **F5/F6** — state the limits in the README rather than fixing them: one model,
   one case, synthetic search gradients.
