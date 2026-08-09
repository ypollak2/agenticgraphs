# v6 audit — AGR v1.5 against its own plan

Stage 4 of 7.

**Verdict: 7 of 7 criteria met. `ab-test-analysis` — the graph that failed every
model for three versions — passes. Contracts satisfied by no recorded model: 1 → 0.**

---

## 1. What changed, measured

75 recordings re-taken across the same 25 graphs × 3 models as v1.4.

| Model | v1.4 | v1.5 | Δ |
|---|---|---|---|
| `qwen3-coder:30b` | 19 / 6 / 0 | **24 / 1 / 0** | **+5 pass** |
| `hermes3:8b` | 7 / 10 / 8 | **14 / 6 / 5** | **+7 pass** |
| `qwen2.5-coder:7b` | 11 / 11 / 3 | 11 / 12 / 2 | flat |

*(pass / fail / unparseable)*

Contract findings across the 27 recorded graphs:

| | v1.3 | v1.4 | v1.5 |
|---|---|---|---|
| ✅ satisfied on every model | 7 | 7 | **13** |
| ⚠️ model-dependent | 16 | 19 | 14 |
| 🚫 satisfied by no model | 4 | 1 | **0** |

Structural gap closed: **103 of 346 silent nodes → 0**, all 83 graphs at
`agr/v1.5`.

The `qwen2.5-coder:7b` result is worth stating plainly: **the smallest model did
not improve.** Declaring what each node produces helps a model that can follow the
instruction. It does not make a 7B model capable of work it could not do. That is
the honest shape of this result, and it is why the scoreboard reports per-model
rather than an average.

---

## 2. Acceptance criteria

| # | Criterion | Target | Actual | |
|---|---|---|---|---|
| E1 | silent nodes 103 → 0 | 0 | **0** (expanded view) | ✅ |
| E2 | all 83 graphs at `agr/v1.5`, lint clean | 83 | 83, 0 errors | ✅ |
| E3 | **`ab-test-analysis` passes on ≥1 real model** | ≥1 | **passes on `qwen3-coder:30b`** | ✅ |
| E4 | live pass rate beats v1.4 (7 clean / 1 unsat) | improve | **13 clean / 0 unsat** | ✅ |
| E5 | no model returns key names where values belong | 0 | 0 across 75 recordings | ✅ |
| E6 | no assert weakened | 0 | **0 expressions changed** (HEAD vs tree) | ✅ |
| E7 | tests green, `make check` clean | yes | **184 tests** | ✅ |

---

## 3. Findings

### F1 — v1.4's published diagnosis was wrong, and the correction is the version

v1.4 shipped stating that `ab-test-analysis` failed because *"the contract has a
joint precondition no single node owns"*, and scoped v1.5 around that.

It was wrong. Both keys were declared on **one** node. What the recordings showed —
and what nobody had read closely enough — was the two nodes *upstream* answering a
question about their job instead of doing it:

```jsonc
{"keys": ["recomputed_effect", "claimed_effect"]}
{"keys_responsible": ["recomputed_effect"]}
```

The correction is written into `docs/agr-v1.5.md` and the README rather than
quietly dropped, because a wrong diagnosis that ships is more damaging than an
open question: it directs the next version's work.

**Process note:** the diagnosis was derived from the *assert* and the *graph*, and
contradicted by the *recordings* — which were already checked in and unread. The
evidence to falsify it existed at the time the claim was made.

### F2 — The genuine joint-precondition case is real but small

6 of 135 asserts do span two producing nodes. They get an advisory, not a
`requires_all` field. Six cases do not justify new schema surface — and §1 of the
plan is a list of what happens to surface that gets added before it is needed.

### F3 — `inputs` was checkable-in-principle for four versions

v1.1 added `inputs` and linted set membership: *does this key exist anywhere in the
graph*. That passes when the only producer runs strictly downstream and the value
can never arrive. Reachability was not checkable until every dependent node had an
output to be reachable *from* — so the weaker check sat there for four versions
looking like a real one.

Zero registry graphs violate it, which means it caught nothing today. It is a trap
that is now closed rather than a bug that was found.

### F4 — 20 nodes were silent because a template was copied 20 times

`mapper` / `worker` / `executor` — the nodes that do the work in map-reduce,
parallel-swarm and planner-executor-verifier — declared nothing, with a `{}`
fixture to match, in 20 graphs. The shape was stamped out before anyone asked what
the node hands to whatever comes next.

Generated graphs propagate a template's omissions at the rate they propagate its
structure. Worth remembering the next time a motif template is written.

### F5 — I misread a partially-flushed log and nearly under-reported the result

Reading the sweep output directly showed `hermes3:8b` producing nothing, and I
started a redundant 25-graph re-run on that basis. The Monitor's own event had the
complete result: 14 pass. Cost was a few wasted minutes of GPU time; the failure
mode — treating a mid-write file as final — is worth naming because it would have
under-reported v1.5's best per-model improvement.

---

## 4. What is left

Nothing blocking. Two things stated rather than fixed:

- **Coverage is still 27 of 83 graphs.** Composites and human-gated graphs have no
  live evidence — an approval gate cannot be replayed.
- **One sample per cell.** A ✅ may have passed by luck.

Both are unchanged from v1.3 and both are in the README.

The next honest step is breadth, not a new spec version: record the remaining 56
graphs, and record more than one sample per cell. **v1.5 is the first version where
the registry has no known structural gap** — which means the next finding will
have to come from evidence, not from reading the spec.
