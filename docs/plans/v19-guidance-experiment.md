# v19 experiment — does edge guidance actually help?

Pre-registered. The decision rule below was fixed in `scripts/guidance_ab.py`
(`CRITERIA`) and committed **before** any live run, so a disappointing result
cannot be rescued by moving the line afterwards.

Mechanism under test: AGR v1.9 edge-carried guidance (`8796359`), the adoption of
arXiv 2609.09153's representation + delivery halves.

---

## 0. Why this cannot be a replay experiment

`_live_score` gates the optimizer by replaying recorded `node_outputs` against a
mutated graph. That is sound for topology, because topology decides which nodes run
and whether a join resolves.

It is useless here. Guidance changes what a node is *told*; a recording's outputs
are fixed; both arms replay identically. **Measuring guidance requires real
inference** — one call per node per arm. This is the cost the plan flagged, and it
is unavoidable rather than an implementation shortcut.

---

## 1. Population

Of the 19 graphs at live 0.0, the failures split cleanly:

| failure type | n | in scope |
|---|---|---|
| wiring/contract — key never produced, terminal unreached | 8 | **no** — v7/v18-class bugs; prose cannot fix a node that never ran |
| value-wrong — node ran, key present, value failed the assert | **11** | **yes** |

### 1.1 Correction after the first pilot — the population is 8, not 11

The first pilot ran `architecture-decision-tournament` and returned delta 0.000 with
guidance verifiably reaching the model. Reading *why* found a third failure class the
value-wrong screen could not see:

The graph is `frame -> design -> judge` with **one** `design` node, no
`parallel_group`, no fan-out. `design` declares `outputs: [proposal, rubric_score]` —
singular. The assert demands `output.designs_scored >= 3`, and `judge` declares
`aggregate: {op: best, over: rubric_score}`, an aggregate over a fan-out **that does
not exist in the topology**. No prose can make one node produce three rival designs
it has no structure to hold. The assert is structurally unsatisfiable.

Screening the other ten for the same defect — a counting assert (`>= N`, N>1) or a
vestigial `aggregate` with no `parallel_group` anywhere — removes three:

| graph | defect |
|---|---|
| `architecture-decision-tournament` | `aggregate` on `judge`, no fan-out; `designs_scored >= 3` |
| `differential-diagnosis-ensemble` | `aggregate` on `adjudicate`, no fan-out |
| `flaky-test-reflexion` | `consecutive_green >= 3`, no loop structure to accumulate it |

**Revised population — 8 graphs:** `blog-production-pipeline`, `alert-noise-reduction`,
`self-healing-ci`, `adverse-event-scanner`, `contract-lifecycle`,
`supplier-risk-monitor`, `bug-triage-and-fix`, `framework-migration`.

`min_graphs_improved` therefore falls from 6-of-11 to **5-of-8** to keep the same
"clear majority" bar.

The three excluded graphs are a finding in their own right, and a v8-class one: they
belong with the 8 wiring failures, not with the guidance candidates. Total honest
split of the 19: **11 structural, 8 guidance candidates.**

### 1.2 A second reason the pilot was uninformative

`judge` already carries v1.8 `criteria` reading *"At least three independent designs
were scored on one rubric…"*. The node was already being told, more specifically than
the edge guidance said it, through a channel that has shipped since v1.8. Where
`criteria` is already present and specific, edge guidance has little room to add
anything — which sharpens the question this experiment asks: **not "does procedural
prose help" but "does prose on the edge add anything beyond the rubric already on the
node".** The revised population favours graphs with nodes that carry no `criteria` at
all.

These fail asserts like `output.designs_scored >= 3` and `output.consecutive_green >= 3`
— the model took the right step and under-delivered. That is what per-step guidance
is for. The 8 wiring graphs are excluded on purpose: including them would let a
mechanism that does nothing look like it did nothing *for a reason*.

---

## 2. Design

- **Paired.** Arm A (guidance stripped) and arm B (guidance present) run the same
  graph, same cases, same model, and the **same seed per episode** — `seed = 7 + ep`.
  The only difference between the arms is the prompt.
- **Repeated.** `episodes_per_arm = 3`. `docs/milestones.md` records two graphs that
  returned both a pass and a fail under identical input; a single run per arm
  measures the sampler, not the graph.
- **Same model as the baseline.** `qwen3-coder:30b` produced 417 of the 549 current
  recordings, so the A/B sits on the same evidence base as the scoreboard.
- **Crash counts as failure**, not as a missing datapoint. A guidance string that
  makes a graph unrunnable must not improve the mean by dropping out of it.

---

## 3. The leak audit — the criterion that matters most

The obvious way to fake a win is to write guidance that states the answer:

```yaml
guidance: "return designs_scored = 3"     # assert: output.designs_scored >= 3
```

The pass rate would climb and would measure **echo**, exactly the contamination
v1.6/T7 found when nodes were handed their own marking scheme. `audit_leak()`
therefore rejects any edge whose prose shares an identifier or a numeric literal
with the graph's own asserts, and **any leak fails the whole experiment**
(`require_zero_leaks`).

This is a deliberately harsh rule. It means guidance has to be domain advice —
"a tournament needs a field, not a favourite" — rather than a restatement of the
rubric. If guidance only works when it leaks, it does not work.

---

## 4. Decision rule (fixed in code)

| criterion | threshold | why |
|---|---|---|
| `min_mean_delta` | +0.25 pass rate | below this the mechanism is not worth the token cost |
| `min_per_graph_delta` | 0.34 | one episode of 3 — a smaller per-graph move is a coin flip |
| `min_graphs_improved` | 6 of 11 | a majority, so one graph cannot carry the result |
| `max_graphs_regressed` | 2 | guidance that helps some and breaks others is not a win |
| `require_zero_leaks` | true | any leak invalidates the run |

**All five must hold.** Anything else is a negative result and gets recorded as one.

---

## 5. What each outcome means

- **Passes** → adopt guidance for the 11, then re-record and let the new recordings
  become the baseline. Only then is L3 (an LLM refiner writing guidance) worth
  building, because only then is there a signal for it to climb.
- **Fails on delta** → the paper's mechanism does not transfer to this registry at
  this model size. Record it in `docs/evidence-history.md` and stop. This is a
  real possibility and the cheap way to find out.
- **Fails on leaks** → the authoring was contaminated, not the mechanism. Rewrite
  the prose and re-run; the delta from a leaking run is not evidence either way.
- **Mixed (helps some, breaks others)** → the interesting case. Report which graphs
  and look for a shape difference, but do not adopt registry-wide on it.

---

## 6. Known limits of this experiment

- **One model.** A result on `qwen3-coder:30b` says nothing about frontier models.
  The registry has made this mistake before (`docs/milestones.md`: "Three local
  models, all small. Nothing is claimed about frontier models").
- **Guidance is hand-authored**, so it tests the *representation and delivery*, not
  the paper's self-evolution. A negative result here kills L3 before it is built; a
  positive result does not prove L3 would work.
- **Small n.** 3 episodes × 1-3 cases per graph. The thresholds are set wide
  precisely because n is small — this is a screening experiment, not a significance
  test, and should be read as the paper's own caveat says: a search trace.
- **Authoring bias.** The guidance was written after seeing each graph's failures.
  That is the honest way to author it, but it means a positive result needs
  confirmation on a case the author did not see before it generalizes.
