# v4 audit — AGR v1.3 against its own plan

Stage 4 of 7. Measured against the registry at the end of stage 3.

**Verdict: 7 of 8 criteria met. The eighth (C3) is met in reporting and open in
action — the four unsatisfiable contracts are named but not yet corrected.**

---

## 1. What the sweep found

75 recordings: 25 graphs × 3 models, all checked in, failures included.

| Model | Pass | Fail | Unparseable |
|---|---|---|---|
| `qwen3-coder:30b` | **19/25** | 6 | **0** |
| `qwen2.5-coder:7b` | 11/25 | 11 | 3 |
| `hermes3:8b` | 7/25 | 10 | 8 |

Of 27 graphs with recordings: **7 satisfied on every model, 16 model-dependent,
4 satisfied by none.**

Three findings, in order of how badly they were mis-attributable:

### F1 — A large share of "model failure" was harness brittleness

`LLMRunner` extracted JSON with one line: `text[text.index("{"):text.rindex("}")+1]`.
It broke on markdown fences, trailing commas, prose wrappers, and Python `True`/
`False`/`None` literals — all routine model output.

Hardening it moved `qwen2.5-coder:7b` from 8→11 passes and 5→3 unparseable, and
`hermes3:8b` from 4→7 and 9→8. Those graphs were never failing; the harness was.

This is the third version running in which the headline problem was the harness
misrepresenting the model, after v1.2's contract-blind prompt. Both were invisible
until real output arrived.

**What remains genuinely unparseable is genuinely unparseable:** `hermes3:8b`
returned `{"execute_test"}` — a set literal, not an object. Correctly counted as a
model failure, and left as one.

### F2 — Model choice dominates, which is why one model proved nothing

`qwen3-coder:30b` passes 19/25 with **zero** parse failures; `hermes3:8b` passes
7/25 with 8. v1.2 shipped its entire live claim on one 7B model. On that evidence
alone, 12 graphs would have looked like bad contracts that a larger model
satisfies perfectly.

The 16 ⚠️ model-dependent graphs are the payoff for recording three: without a
second model there is no way to separate "this contract is unsatisfiable" from
"that model was weak", and this registry would have drawn the wrong conclusion 16
times.

### F3 — 4 contracts are satisfied by no model, and they share a shape

`ab-test-analysis`, `earnings-call-digest`, `differential-diagnosis-ensemble`,
`benchmark-driven-optimization-search`.

All four assert on **specific sub-keys** (`output.recomputed_effect`,
`output.figures`, `output.consensus`, `output.suite_green`) while declaring only
`outputs: [output]`. The model is told to return `output` and correctly returns
*an* object — just not one with the keys the contract needs.

That is the same root cause as v1.2's finding, one level down: the contract exists
but is not told to the model. It is a **correctable** defect, not evidence that
the task is impossible — and correcting it means declaring the keys, never
relaxing the assert.

---

## 2. Acceptance criteria

| # | Criterion | Target | Actual | |
|---|---|---|---|---|
| C1 | ≥25 graphs recorded across ≥3 models | 25/3 | 27 graphs, 3 models, 75 recordings | ✅ |
| C2 | per-model pass rate **and** disagreement reported | yes | scoreboard shows per-model %, ⚠️ split, 🚫 none | ✅ |
| C3 | every all-model failure fixed **or** labelled | all | 4 labelled; **0 fixed** | ⚠️ |
| C4 | `agr triggers` emits valid artifacts for all 3 kinds | 3 | cron, github-actions, webhook + round-trip test | ✅ |
| C5 | killed run resumes to identical terminal state | yes | trace-equality test, partial and full journal | ✅ |
| C6 | budget cap halts a run | yes | `steps_max` and `usd_max`, checked before execution | ✅ |
| C7 | no accepted-and-ignored fields remain | 0 | `approval.timeout`, `retries.backoff` deleted from schema and 10 graphs | ✅ |
| C8 | trace locks hold, tests green, `make check` clean | yes | 157 tests | ✅ |

---

## 3. Findings against the plan's own rules

The plan set two rules from v1.2's lessons. Both held, and one was nearly broken:

**"No field without an executing consumer in the same version."** `triggers` ships
with `agr triggers`; `durability` with `--resume-from`; `budget` with enforcement
that halts. `approval.timeout` and `retries.backoff` were **deleted** rather than
carried a third version — the rule applied retroactively, which is the harder half.

**"Every criterion falsifiable by something other than a fixture."** C5 asserts
trace equality against a real truncated journal; C6 uses a cap of 2 and checks the
run stopped short; C7 greps the shipped schema. C1–C3 are measured against 75
recordings of real model output.

### F4 — C3 is reported but not acted on (blocking)

The four unsatisfiable contracts are named in `docs/contract-findings.md` and
marked 🚫 in the scoreboard. None has been corrected. The plan's own wording was
"fixed **or** labelled", so this is technically met — but F3 shows the cause is a
missing declaration, which is cheap to fix, and labelling something as broken when
you know how to fix it is the weaker half of the disjunction.

### F5 — the sweep covers 27 of 83 graphs

Recordings exist for the 25 smallest graphs plus 2 from v1.2. The other 56 —
including every composite and every human-gated graph — have no live evidence.
Composites are excluded partly for a real reason (a human gate cannot be replayed)
and partly for an unexamined one (they are slower).

### F6 — one recording per graph per model

Each cell is a single sample. Model output varies between runs; a graph marked ✅
may have passed by luck and a ❌ may have been unlucky. Nothing here distinguishes
them, and the scoreboard does not claim otherwise.

---

## 4. Stage 5 — closure record

| Finding | Resolution |
|---|---|
| F1 harness brittleness | **Fixed.** Tolerant JSON extraction: markdown fences, trailing commas, prose wrappers, Python `True`/`False`/`None`, and a balanced-prefix fallback for truncated replies. Genuinely malformed output still fails. |
| F4/C3 correct the 4 contracts | **Attempted and did not work — see below.** |
| F5 coverage | Scoreboard and README now state 27 of 83, and why composites have none. |
| F6 single sample | Both say plainly that each cell is one sample. |

### The attempted fix failed, and that is the finding

The four 🚫 contracts assert on sub-keys (`output.recomputed_effect`,
`output.consensus`) while declaring only `outputs: [output]`. The diagnosis in F3
was that the model is never told which keys it owes, so the fix was to declare
them on the terminal node and re-record across all three models.

**Result: 0 of 12 runs passed.** The failure mode moved — from `output` missing
entirely to `output` present with *some* keys — but none satisfied the contract.

The diagnosis was one level too shallow. `output` is assembled by the **terminal**
node out of facts that **upstream** nodes established:
`ab-test-analysis` needs `claimed_effect` from intake and `recomputed_effect` from
the analysis step. Declaring both on the terminal asks a single node to report
facts it never had. The declaration is now accurate and still insufficient.

**The real gap: the I/O contract is per-node, the verification contract is
graph-level, and nothing connects them.** No lint asks whether the nodes that run
before a verifier actually produce what the verifier asserts on. That is why 4
contracts can be structurally valid, pass 157 tests, and be satisfiable by no
model — and it is a v1.4 item, not something to fake closed here.

The declarations are kept: they are correct as far as they go, and they moved the
failure from "no contract at all" to "contract stated in the wrong place", which
is what made the real cause visible.

**C3 outcome, stated exactly:** 4 contracts labelled, 0 fixed, cause diagnosed and
carried forward as the top v1.4 item. The plan's wording ("fixed or labelled") is
met; the intent behind it is not, and this section exists so that is not mistaken
for success.
