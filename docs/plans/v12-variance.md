# v12 — one sample was measuring luck

Not a feature. A measurement, and a correction to numbers this repo has published
since v1.3.

## Why it was run

v1.7's re-record produced 10 improvements and **5 regressions**. Seeding a goal has
no mechanism for breaking a graph that passed, so the regressions were resampled —
and two graphs returned both a pass and a fail under identical input.

That made the registry's own stated limit the live question:

> *"Each cell is one sample. Model output varies between runs; a ✅ may have passed by
> luck and a ❌ may have been unlucky. Nothing here distinguishes them."*

Nobody knew whether that meant two cells or thirty. So: 3 samples of all 83 graphs on
`qwen3-coder:30b`, tools off, goals seeded — 249 runs.

## The result

| cell verdict | count | share |
|---|---|---|
| stable pass (3/3) | 57 | 70% |
| stable fail (0/3) | 9 | 11% |
| **unstable** | **16** | **20%** |

*82 of 83 cells reached 3 samples; `feature-delivery-lifecycle` reached 1 (below).*

**One cell in five returns a different verdict on identical input.** Every
single-sample comparison this repo has published — including v1.7's own — sits on top
of that.

Registry-wide, once cells had repeats:

| | before | after |
|---|---|---|
| 🚫 satisfied by no model | 14 | **8** |
| 🎲 same model, different answer | 2 | **18** |
| ✅ satisfied on every model, every sample | 50 | 40 |

## Six graphs were never unsatisfiable

The 🚫 count did not fall because anything improved. It fell because these were
labelled on one unlucky draw:

| graph | actual, at n=3 |
|---|---|
| `clinical-literature-triage` | 67% |
| `literature-review-swarm` | 67% |
| `docs-code-sync-audit` | 67% |
| `incident-lifecycle` | 67% |
| `product-listing-pipeline` | 67% |
| `framework-migration` | 33% |

`literature-review-swarm` is listed in `contract-findings.md` under 🔌 *unsatisfiable by
construction* — "needs a paper corpus." It passes 2 of 3 times. Either the label is
wrong or those passes are fabrication, and **a single sample could not tell you
which.** That is the whole finding in one row.

## Nine that are real

> **Superseded by Round 2 — this claim did not survive a second model.**
> `incident-triage-router` is 0/3 here and **3/3 on `devstral:24b`**. It is not
> unsatisfiable; it is model-specific, and one model at n=3 could not tell the
> difference. Left in place because the correction is the point: "0 of 3, not 0 of 1"
> was a real improvement over one sample and *still* not enough.

0 of 3, not 0 of 1 — this is what evidence of an unsatisfiable contract looks like:

`alert-noise-reduction` · `flaky-test-reflexion` · `incident-triage-router` ·
`invoice-reconciliation` · `self-healing-ci` · `soc-alert-investigation` ·
`supplier-risk-monitor` · `test-suite-generation` · `trial-eligibility-screener`

## A third outcome the grading never had

Three graphs did not fail — they returned replies that could not be parsed at all. A
JSON array where an object was required, or an object truncated mid-emit:

```
hiring-lifecycle        ["Alex Chen", "Jamie Smith", "Taylor Reed"]
feature-delivery-lifecycle  ["Ensure consistent use of camelCase for variable names…"]
```

`clinical-protocol-lifecycle` produced **ERROR, then FAIL, then PASS** across three
identical runs.

An unparseable reply is neither a pass nor a contract failure, and nothing in the
scoreboard counts it. `feature-delivery-lifecycle` is stuck at n=1 for exactly this
reason: two of its three samples were unparseable.

## The script defect this exposed

`record_live.py` wrapped its whole sample loop in one `try`, so the **first** bad reply
discarded that graph's remaining samples. A variance run left three graphs at n=1 —
precisely the condition it existed to remove. Now per-sample: a model that fails to
emit JSON is an observation about the cell, not a reason to stop observing it.

## What this changes

1. **No claim from a single sample.** Not "this graph passes", not "no model satisfies
   this", not "version N moved the number." 73 cells are still n=1.
2. **v1.7's J8 stands as written** — that re-record measured variance, and this
   quantifies the variance it was measuring. 20% is more than enough to produce
   10 improvements and 5 regressions from noise alone.
3. **`assert-grounded` matters more, not less.** All 249 runs here made 0 tool calls.
   Stability and truth are different axes: a graph can be perfectly stable at 3/3 and
   still be fabricating, which is what a 0-tool-call pass is.

## What is still not known

- **One model.** `qwen3-coder:30b` only. Whether 20% is typical or particular to it is
  unmeasured; the other three models remain at n=1.
- **Three samples is a floor.** It separates 0/3 and 3/3 from the middle. It does not
  estimate a rate — a 3/3 cell could be a 90% cell.
- **Nothing here says a stable pass is earned.** See point 3.

---

# Round 2 — a second model, and the finding gets worse

`qwen3-coder:30b` showed 20% of cells returning different verdicts on identical
input. The obvious question: is that the model, or the setup? So the same 83 graphs
were run 3x on **`devstral:24b`** — different family (Mistral), comparable size, same
harness, same goals seeded, same tools-off conditions. Model identity is the only
variable.

| | `qwen3-coder:30b` | `devstral:24b` |
|---|---|---|
| stable pass (3/3) | 57 | 17 |
| stable fail (0/3) | 9 | 10 |
| **unstable** | **16 (20%)** | **23 (46%)** |
| cells scored | 82 | 50 |

**It is not the model. It is worse on the second one — nearly half its cells disagree
with themselves.**

## The models do not agree about which graphs are stable

Of 49 cells scorable on both, **28 (57%) fall into different stability classes**. A
contract that is a rock-solid 3/3 on one model is a coin flip or a flat 0/3 on the
other:

| | example |
|---|---|
| pass on A, unstable on B | `bug-triage-and-fix`, `contract-lifecycle`, `postmortem-writer` |
| pass on A, fail on B | `anomaly-investigation`, `cost-routed-research`, `ediscovery-triage` |
| fail on A, pass on B | `incident-triage-router` |
| unstable on A, fail on B | `clinical-literature-triage`, `incident-lifecycle` |

`incident-triage-router` is the sharpest: **0 of 3 on `qwen3-coder:30b`, 3 of 3 on
`devstral:24b`.** Round 1 listed it under "genuinely unsatisfiable — 0 of 3, not 0 of
1". It is not unsatisfiable. It is model-specific, and one model at n=3 could not tell
the difference either.

## One graph in the registry has real evidence of an unsatisfiable contract

Failing 0/3 on **both** model families — six independent attempts:

    flaky-test-reflexion

That is the whole list. The registry currently publishes 6 as 🚫 *satisfied by no
model*. One survives two-family, three-sample scrutiny.

## Registry effect

| | before repeats | after `qwen3` n=3 | after `devstral` n=3 |
|---|---|---|---|
| 🚫 satisfied by no model | 14 | 8 | **6** |
| 🎲 same model, different answer | 2 | 18 | **37** |
| ✅ satisfied every model, every sample | 50 | 40 | **24** |

The ✅ column is the one to look at. It has more than halved — not because anything
broke, but because 26 graphs that looked clean were only ever measured once.

## Caveats, stated

- **`devstral:24b` is incomplete: 50 of 83 cells reached 3 samples.** The 25 unfinished
  are the heavy composites (search, fan-out, retry loops) — they take ~10 minutes each,
  and three separate background runs were terminated part-way. Its 46% is therefore
  measured on a set skewed toward primitives, and could move either direction when the
  composites land.
- **Unparseable replies reduce `n` rather than counting as failures.** `devstral:24b`
  emitted markedly more of them — JSON arrays where objects were required, truncation
  mid-object, and once `float('inf')`, which is Python, not JSON. Cells where it never
  produced 3 parseable runs are excluded entirely, so 46% describes the cells where it
  *could* be scored.
- **All runs made 0 tool calls.** Stability is not truth. A stable 3/3 with no tool call
  is a model that reliably says the same thing, which is not the same as a model that is
  right.

## What follows

The registry's live evidence has been reporting single draws from distributions with
substantial spread. That is not a flaw in any one graph or model — it is what the
measurement was. Concretely:

1. **🚫 *satisfied by no model* cannot be claimed from one model.** `incident-triage-router`
   disproves it directly. The label needs agreement across families at n>=3.
2. **77 cells are still n=1.** Nothing should be concluded from them in either direction.
3. **A fourth verdict is needed.** Pass / fail / unsatisfiable has no room for "the model
   did not emit parseable output", which happened often enough here to silently shrink
   the denominator.
