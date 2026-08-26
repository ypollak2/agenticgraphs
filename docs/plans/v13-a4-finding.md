# A4 — the stale-recording measurement

The M11 plan said this number would run first because it could reorder the plan.
It does.

Reproduce: `uv run python scripts/audit_recordings.py --json reports/a4.json`
(exits non-zero while any verdict flip stands). Measured at `a6f8464`.

---

## 1. The result

| Question | Answer |
|---|---|
| Recordings on disk | **560** across 83 graphs |
| Counted in the published evidence | **560 of 560** — every file on disk is a result row in some `profile.json` |
| `graph.yaml` changed at all since the recording was committed | **78 (14%)** |
| **Shape** changed — the parts that decide replay and grading | **71 (13%)** |
| Verdict flipped without the recording being re-recorded | **5 confirmed** |
| Graphs whose **published evidence tier** depends on a stale recording | **10 of 83** |

Not zero. A4 is a fix, not insurance.

## 2. Staleness is not spread evenly — it is one cohort

| Model | Stale | Total |
|---|---|---|
| `qwen2.5-coder:7b` | **30** | 30 |
| `hermes3:8b` | **23** | 23 |
| `gpt-4o` | **18** | 25 |
| `devstral:24b` | 0 | 235 |
| `qwen3-coder:30b` | 0 | 247 |

Every stale recording belongs to one of the three secondary models, and two of
them are stale in full. The two primary models were re-recorded on 2026-08-11
(`10458db`, `fcdb435`, `a6f8464`); the other three have not been re-recorded since
the v1.3/v1.5 era and were never revisited.

`docs/live-coverage.md` opens with "**83 of 83 graphs recorded**, across
`devstral:24b`, `gpt-4o`, `hermes3:8b`, `qwen2.5-coder:7b`, `qwen3-coder:30b`."
That is true as a file count. As an evidence claim it now needs a caveat: three of
those five models are reporting on graph shapes that no longer exist.

## 3. What changed under them — and what did not

| Dimension | Recordings | Graphs |
|---|---|---|
| node `outputs` declarations | 61 | 35 |
| `goal` block | 26 | 22 |
| `state` block | 25 | 21 |
| **`verification` / `termination` (the contract)** | **0** | **0** |

**The contract never moved.** No recording is being judged against an assert its
model was not shown — which is the worst version of this finding, and it did not
happen. `LLMRunner` puts the scoped asserts in the prompt, and those asserts are
the same ones grading the reply today.

What did move is v1.5 (*every node declares*, which added `outputs` to 103 nodes)
and v1.7 (`goal` / `state`). So the live failure mode is narrower and specific: a
model that was **never told which keys to return** is now graded against a key
declaration that postdates its answer.

`docs-code-sync-audit` shows it exactly. The recording is from v1.3, when `plan`
declared bare `outputs: [tasks]` and `work` declared none. Today the graph declares
`tasks: list[{doc:str, snippet:str}]` and `work_result: '{doc:str, command:str,
exit_code:int}'`. The `hermes3:8b` row now reads:

```
passed: false      assert_failures: []      goal_missing: ""
```

**Failed, with nothing recorded as having failed.** The verdict comes from the
shape check; the scoreboard has no column for it. That is the same misattribution
`extract_json`'s docstring warns about — counting harness and spec drift as a
model failure, inside the very sweep built to measure model failure.

## 4. The five verdict flips

Same recording bytes, graded at the commit that wrote them and graded at HEAD:

| Graph | Model | Case | |
|---|---|---|---|
| `alert-noise-reduction` | `hermes3:8b` | single-item | PASS → FAIL |
| `benchmark-driven-optimization-search` | `hermes3:8b` | happy-path | PASS → FAIL |
| `docs-code-sync-audit` | `hermes3:8b` | first-attempt-verified | PASS → FAIL |
| `docs-code-sync-audit` | `qwen2.5-coder:7b` | first-attempt-verified | PASS → FAIL |
| `escalation-summarizer` | `hermes3:8b` | happy-path | FAIL → PASS |

**Read this number as a floor, not a total.** The test only reaches cells holding
exactly one sample on both sides — **74 of 560 rows**. A cell with three samples
cannot be compared, because the profile does not record which result row came from
which recording file, and a re-record may legitimately have added samples. Within
what is comparable: **5 of 65 stale cells flipped, 0 of 9 fresh cells did** — and
that fresh denominator is far too small to carry weight on its own.

*A first draft of this audit reported 8 flips. Three were artifacts: verdicts were
keyed by `(case, model)`, so on a flaky cell the last sample silently overwrote the
others and sample ordering read as a verdict change. The audit now refuses any cell
it cannot pair one-to-one.*

## 5. What it does to the published numbers

Recomputing every tier with stale recordings dropped:

| Tier | Published | Without stale evidence |
|---|---|---|
| ✅ satisfied on every model | 13 | **21** |
| 🎲 flaky | 50 | 49 |
| ⚠️ models disagree | 15 | **7** |
| 🚫 satisfied by no model | 5 | **6** |

Ten graphs move. Eight of the fifteen ⚠️ *models disagree* labels exist **only
because a stale recording disagreed** — and in every one of those eight, the
dissenting model is one of the three stale ones. `supplier-risk-monitor` moves the
other way, to 🚫, when its stale passing row is dropped.

**Excluding is not correcting, and 21 is not the true ✅ count.** Dropping a stale
row removes that model from the graph's denominator entirely — the exact criticism
the README already levels at itself over the 13 unscorable cells ("excluded from
the percentages rather than penalised by them"). The honest reading is narrower and
more useful:

> Eight of the fifteen model disagreements are **unattributable**. They may be a
> weak model, or a model answering a question the graph no longer asks, and the
> current evidence cannot tell those apart.

The fix is re-recording, not exclusion.

## 6. How this reorders M11

1. **A4 becomes blocking for M12, not insurance.** D2's evidence budget is
   measured against a baseline that is 13% stale in the secondary models. Adding
   48 graphs on top of that compounds an error rather than diluting it.
2. **New work item — re-record the secondary cohort.** 78 recordings across
   `qwen2.5-coder:7b`, `hermes3:8b`, `gpt-4o`, against current shapes. This is the
   remediation; `graph_sha` is only the detector that would have caught it.
3. **`scripts/audit_recordings.py` joins the gate.** It already exits non-zero on
   a flip. Once recordings carry `graph_sha` the git reconstruction becomes a
   fallback for historical files rather than the primary method.
4. **A silent failure needs a column.** A run that fails with `assert_failures: []`
   and no `goal_missing` is failing a shape check that nothing reports.
   `shape_violations` exists on `RunReport` and is dropped before serialisation.
   Surface it in `profile.json` and in the scoreboard.
5. **`docs/live-coverage.md` needs its caveat now** — before M12, not after. The
   five-model breadth claim is currently stronger than the evidence under it.

## 7. What would have prevented it

`record_live.py` stamping `graph_sha` at capture, and the gate refusing to count a
recording whose `graph_sha` no longer matches. The cost is one hash per recording.
The gap ran from v1.3 to now and cost 71 recordings, 10 published tiers, and one
breadth claim.
