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
| stable pass (3/3) | 57 | 21 |
| stable fail (0/3) | 9 | 13 |
| **unstable** | **16 (20%)** | **36 (51%)** |
| cells scored | 82 | 70 |

**It is not the model. It is worse on the second one — nearly half its cells disagree
with themselves.**

## The models do not agree about which graphs are stable

Of 69 cells scorable on both, **39 (57%) fall into different stability classes**. A
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

## Four graphs have cross-family evidence of an unsatisfiable contract

Failing 0/3 on **both** model families — six independent attempts each:

    flaky-test-reflexion
    self-healing-ci
    supplier-risk-monitor
    trial-eligibility-screener

Four graphs. The registry published **14** as 🚫 *satisfied by no model* before repeats
existed. Four survive two-family, three-sample scrutiny.

## Registry effect

| | before repeats | after `qwen3` n=3 | after `devstral` n=3 |
|---|---|---|---|
| 🚫 satisfied by no model | 14 | 8 | **5** |
| 🎲 same model, different answer | 2 | 18 | **50** |
| ✅ satisfied every model, every sample | 50 | 40 | **13** |

The ✅ column is the one to look at. **50 graphs looked clean; 13 still do.** Nothing
broke — the other 37 had simply been measured once each.

## Caveats, stated

- **The composites landed, and instability went UP: 46% -> 51%.** The earlier figure was
  measured on 50 cells skewed toward primitives; adding the heavy composites (search,
  fan-out, retry loops) made it worse, which is the direction more nodes and more chances
  to drift would predict. 70 of 83 cells now at n=3.
- **13 cells could not reach n=3 at all** — 12 at n=2, 1 at n=1. These are not slow, they
  are cells where `devstral:24b` repeatedly fails to emit parseable output. See below.
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

## Cells that cannot be scored at all

13 cells never reached n=3, and not because they are slow. `devstral:24b` repeatedly
fails to emit parseable output for them, and a sample that fails to parse writes no
record — so it reduces `n` rather than counting as anything.

`architecture-decision-tournament` is the clearest case: **6 attempts, 0 valid
samples**, three distinct failure shapes:

```
unparseable JSON:  '{"proposal": {...}, "rubric_sc…          (truncated mid-object)
TypeError:         '>' not supported between 'dict' and 'dict'
unparseable JSON:  '{"rubric": {"latency_bound": 200,   # milliseconds   (a comment)
```

This produces three separate reporting problems:

1. **Silent denominator shrinkage** — a rate is computed over fewer attempts than were
   requested, with no indication.
2. **Selection bias** — a model that often cannot emit valid JSON is *excluded from* the
   percentages rather than *penalised by* them. The worst pairings vanish.
3. **Non-termination** — a cell with reliable parse failure can never reach `n`, so no
   amount of resampling fixes it. It is permanently unscoreable and permanently invisible.

Pass / fail / unsatisfiable has no state for "this model cannot be scored on this
graph". That is a fourth verdict, and adding it is a design decision rather than a
patch — recorded here rather than guessed at.

## A harness defect this surfaced

The `TypeError` above is **not** a model failure. `kind: search` scores candidates with
`>`, and when a node returns a dict where a number was expected the comparison raises.
The harness has no type guard at that point, and the resulting crash is currently
recorded as if the model had produced unparseable output — misattributing a harness bug
to the model. Unfixed; noted.
