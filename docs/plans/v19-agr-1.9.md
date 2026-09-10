# v19 — "The optimizer is climbing a metric pinned at 1.0" (AGR v1.9)

Scope: adopt the mechanisms of *Procedural Graphs: Self-Evolving Execution
Structures for LLM Agents* (arXiv 2609.09153) into AGR. Full paper analysis in
[`docs/research/2609.09153-procedural-graphs.md`](../research/2609.09153-procedural-graphs.md).

Stage 1 of this plan adds **no new schema**. The schema bump is stage 2, and it is
gated on stage 1 producing a measurable difference.

---

## 0. The evidence

`agr optimize` gates every mutation on `_cases_still_pass` (`src/agenticgraphs/mutate.py:39-57`),
which replays golden cases through `MockRunner(case["node_outputs"])` — **canned
node outputs**. Here is what that gate can see, measured across all 83 graphs:

| metric | distribution |
|---|---|
| `measured.pass_rate` — mock, **what the gate reads** | **1.0 for all 83** |
| `measured_live.pass_rate` — real models, what nothing optimizes | 0.0 ×19 · 0.25 ×6 · 0.625 ×1 · 0.75 ×18 · 0.778 ×1 · 1.0 ×38 |

The optimizer is hill-climbing a metric that is already at its ceiling on every
graph in the registry. It cannot reject a mutation for lowering quality — only for
breaking schema or lint. **45 of 83 graphs have live headroom the gate is blind to.**

The blindness is structural, not incidental. Because `node_outputs` are canned, the
mock replay produces identical results for any two graphs that differ only in prompt
text. So a change to *what a node is told* is unmeasurable by this gate **in
principle**. That single fact determines the ordering of everything below: the
paper's central artifact is per-edge guidance prose, and under today's gate adding it
would be untestable.

The failure signal we would need already exists and is already structured:

| `failure_kinds` across live results | count |
|---|---|
| `assert` | 148 |
| `stall` | 27 |

plus per-result `deadlocked`, `parse_failures`, `unreached_terminals`,
`shape_violations`, `timeouts` (`evalcmd.py` `_block`).

**agenticgraphs already measures the right thing (`measured_live`) and already
optimizes the wrong one (`measured`).** Redirecting the gate is the whole unlock.

---

## 1. What the paper actually does

Three mechanisms, in the paper's own dependency order:

1. **Typed attributed triplets.** `(procedure, relation, procedure)`, four relation
   types, edges carrying `condition` / `guidance` / `pitfalls` prose.
2. **Generative guidance.** An LLM `Ψ` localizes the active node, reads its 2-hop
   neighborhood, and *generates* situational advice appended to the solver prompt —
   a soft bias, not a constraint on legal actions.
3. **Validation-gated refiner.** Offline, an LLM contrasts high- vs low-scoring
   trajectories, proposes topology/attribute edits, and commits only if the candidate
   matches or beats the current graph on a held-out validation split (ties accept).
   Rejected candidates are logged and fed back as negative evidence.

Reported: 19 wins / 2 ties / 3 losses over 24 model×benchmark settings; a broken
expert prior recovered 58.93% → 92.86% on MultiChallenge.

---

## 2. Architecture

Four layers. The dependency order is forced — each layer is unmeasurable without the
one below it.

```
┌─ L3  EVOLUTION ────────────────────────────────────────────────┐
│  op_llm_refine(doc, ctx)  ──proposes──▶ candidate doc          │
│    reads ctx["failures"]  (assert/stall taxonomy)              │
│    reads ctx["rejected"]  (rejection memory ← lineage.yaml)    │
│                    │                                           │
│                    ▼  gate: score(G') >= score(G) on VAL split │
│         accept ─▶ auto/mutations branch    reject ─▶ lineage   │
└────────────────────────────┬───────────────────────────────────┘
┌─ L2  DELIVERY ─────────────▼───────────────────────────────────┐
│  _prompt_text(node, bb, bound)          harness.py:727         │
│    + local subgraph: in/out edges, 1-hop, with edge guidance   │
│    (structured serialization — NOT a second LLM call, yet)     │
└────────────────────────────┬───────────────────────────────────┘
┌─ L1  REPRESENTATION ───────▼───────────────────────────────────┐
│  AGR v1.9 edge attrs: guidance / condition / pitfalls          │
│    spec/agr-graph.schema.json  (additionalProperties: false    │
│    → schema bump is mandatory, not optional)                   │
└────────────────────────────┬───────────────────────────────────┘
┌─ L0  SCORING ──────────────▼───────────────────────────────────┐
│  _cases_still_pass (mock, boolean, pinned at 1.0)              │
│      ──replace──▶ eval_graph(live=True) → scored pass_rate     │
│  + val split sourced from EPISODES, not cases.yaml             │
└────────────────────────────────────────────────────────────────┘
```

### L0 — Scoring (the unlock)

Swap the gate from mock-boolean to live-scored. **The scoring engine already
exists**: `eval_graph(name, live=True)` uses `LLMRunner` and already computes
`pass_rate` and `per_model_pass_rate` (`evalcmd.py:131, 198, 244`). `mutate.py`
simply does not call it. This is a redirect, not a new subsystem.

The split is the hard part, and it **cannot come from `cases.yaml`**:

| cases per graph | graphs |
|---|---|
| 1 | 30 |
| 2 | 50 |
| 3 | 3 |

You cannot hold out from two. The split has to come from **episodes** — repeated
live runs at fixed seeds across a pinned model set. The recording layer already does
this: the `#1`/`#2` suffixes (`first-attempt-verified@devstral-24b#1.json`) are
repeat episodes of one case, and `measured_live` already aggregates n=8 for a
2-case graph.

**Blocker, measured:** only two models have *current* recordings.

| model | current | superseded |
|---|---|---|
| `qwen3-coder:30b` | 417 | 247 |
| `lfm2.5:8b` | 130 | 0 |
| `devstral:24b` | **0** | 235 |
| `gpt-4o` | **0** | 25 |
| `qwen2.5-coder:7b` | **0** | 30 |
| `hermes3:8b` | **0** | 23 |

All 560 superseded recordings share one `reason` — the bulk invalidation from the
assert-leak fix (the same fix `_prompt_text`'s comment at `harness.py:735-737`
describes). So a cross-model held-out split has exactly **two** models available
today, one of which (`lfm2.5:8b`) is the weak one. **Re-recording on at least one
more mid-size model is a prerequisite for L0, not an optional extra.**

Note also that `reason` is bulk provenance, not per-run failure diagnosis:
`superseded_by`/`reason` cannot serve as the refiner's negative signal. That has to
come from `failure_kinds`.

### L1 — Representation

`edges` today carries only `from` / `to` / `when` / `kind`, with
`additionalProperties: false` — so a schema bump is mandatory. v1.9 adds optional
`guidance`, `condition`, `pitfalls`.

The precedent is exact: `criteria` landed in v1.8 as prose on a node and is the one
prose field that reaches a model today (`harness.py:738`). Same
schema → adapter → prompt path, one hop over to edges.

**Do not import the paper's four relation types** (`LEADS_TO`, `TRIGGERS`,
`PROVIDES_INPUT_FOR`, `CONVERGES_TO`). AGR's `kind: flow|error|compensate` is already
a relation vocabulary with real runtime semantics — joins, back-edge lint, dead-branch
settlement (`_Readiness`, `harness.py:770`). The paper's types are prompt-facing
labels with no execution meaning; layering them on creates two vocabularies where only
one has teeth. Put the paper's *semantics* in the attributes; keep `kind` as the typed
relation.

### L2 — Delivery

`_prompt_text` (`harness.py:727`) is a single function and the only wiring point. Add
local subgraph context: predecessors, successors, and the guidance on the edges that
reached this node.

Deliberately **not** the paper's generative `Ψ` first. The paper's own efficiency
ablation found that full-graph injection *and* full-graph generative guidance both
underperformed the localized variant — the win is **localization, not generation**.
Structured serialization captures that for zero extra inference. Generation becomes an
L2.5 experiment, gated on L0 showing the structured version moved live pass rate.

This is also the fix for the repo's own standing finding: `prompt_seed` has been in
the schema since M0, is declared by 0 of 34 specialities, and is read by **0 lines of
runtime code** (`docs/architecture-m11.md:95-96`). Same function, same patch.

### L3 — Evolution

A fourth entry in `OPERATORS` (`mutate.py:184`), matching the existing
`(doc, ctx) -> list[str]` signature — the plug point is already clean. It differs
from the three existing operators in being non-deterministic, which forces three
changes:

- **Input.** `ctx["failures"]` built from `measured_live` results — the
  `assert`/`stall` taxonomy, not raw trajectory text. Structured failure kinds are a
  better refiner prompt than the paper's trajectory diffing.
- **Gate.** Scored comparison from L0, replacing the per-operator boolean revert at
  `mutate.py:199-201`.
- **Rejection memory.** `_lineage_append` already accepts an arbitrary dict, so
  logging rejected candidates is nearly free — but `lineage.yaml` records only
  *accepted* mutations today, so this is a semantic extension (add `status:
  accepted|rejected`), not a new file.

Isolation needs no design work and is **stronger than the paper's**:
`commit_autonomous_mutation` → `auto/mutations`, never pushed, never `main`
(`src/agenticgraphs/autonomy.py`, `docs/autonomy.md`). In the paper, a committed graph
*is* the production graph.

---

## 3. Files

| layer | file | change |
|---|---|---|
| L0 | `src/agenticgraphs/mutate.py` | `_cases_still_pass` → `_val_score`; per-operator revert → scored accept/reject |
| L0 | `src/agenticgraphs/evalcmd.py` | expose split selection (model/seed sets) on `eval_graph` |
| L0 | `graphs/*/*/val.yaml` | **new** — pinned validation model+seed set per graph |
| L0 | `graphs/*/*/live/` | re-record on ≥1 additional mid-size model |
| L1 | `spec/agr-graph.schema.json` | edge `guidance` / `condition` / `pitfalls` |
| L1 | `docs/agr-v1.9.md` | **new** spec doc (follows every prior bump's convention) |
| L1 | `src/agenticgraphs/adapters.py` | carry edge attrs into LangGraph/CrewAI/AutoGen emission |
| L2 | `src/agenticgraphs/harness.py:727` | `_prompt_text` — local subgraph + edge guidance + `prompt_seed` |
| L3 | `src/agenticgraphs/mutate.py` | `op_llm_refine` + refiner prompt |
| L3 | `graphs/*/*/lineage.yaml` | `status: accepted\|rejected` |

---

## 4. Stages, each with a kill gate

**Stage 1 — L0 only, no new schema.** Re-record on a third model, then point the
existing three operators at the live score.
*Kill gate:* does scored gating change any accept/reject decision on the 45 graphs
with headroom? **If it changes nothing, stop.** Everything above L0 is unmeasurable.

**Stage 2 — L1+L2 on the 19 graphs at live 0.0.** Hand-author edge guidance; measure.
The 19: `invoice-reconciliation`, `vendor-comparison-matrix`, `blog-production-pipeline`,
`alert-noise-reduction`, `incident-lifecycle`, `self-healing-ci`,
`regulatory-filing-lifecycle`, `adverse-event-scanner`,
`differential-diagnosis-ensemble`, `trial-eligibility-screener`, `hiring-lifecycle`,
`performance-cycle-summarizer`, `contract-lifecycle`, `supplier-risk-monitor`,
`vuln-remediation-lifecycle`, `architecture-decision-tournament`, `bug-triage-and-fix`,
`flaky-test-reflexion`, `framework-migration`.
*Kill gate:* **if hand-written guidance cannot move a 0.0, an LLM refiner writing
guidance will not either.** Stop before L3.

Note that these skew heavily toward composites — the same population v7 found was
failing on inherited phase contracts. **Hypothesis to test, not assume: some fraction
of the 19 are still v7/v18-class contract bugs, not guidance-starved graphs.** Diagnose
before authoring prose at them; prose that papers over a wiring bug is worse than the bug.

**Stage 3 — L3 behind `AGR_AUTONOMOUS`**, one graph, many rounds, everything to
`auto/mutations`.

**Stage 4 — generative `Ψ` (L2.5) and rejection memory**, only if stage 3 shows
repeated-direction failures. The paper found this real enough to build a mechanism for
(their Appendix E.2 shows rounds 3/4/6 all rolled back on one benchmark).

---

## 5. Costs and risks

**Scored gating costs real inference, unavoidably.** Recordings cannot be reused: a
mutated graph emits different prompts, so old `node_outputs` no longer apply. Order of
magnitude — a 4-8 node graph on `qwen3-coder:30b` (~15s p50/call) is ~1-2 min/episode;
a 20-episode validation is 20-40 min per round per graph. Tractable locally; would be
prohibitive on a metered API. This is why the local-model routing matters.

**The 1.0 ceiling cuts both ways.** 38 graphs already pass live at 1.0. On those, the
paper's accept-ties rule lets a refiner churn topology indefinitely with no score signal
opposing it. **Disable L3 for any graph at val 1.0** rather than adopt the tie rule
there. Where L3 does run, adopt the paper's stated caveat verbatim: with a small
validation set, accept/reject turns on one or two episodes and should be read as a
search trace, not a significance test.

**Overfitting to the validation split** is the paper's main exposure and becomes ours.
The cross-model split (train on one model, validate on another) is a *stronger*
generalization test than the paper's and is the main mitigation — but it only works once
there are ≥3 current models to split across.

**Sampling noise is already documented here.** `docs/milestones.md` records that v1.7's
re-record produced *two graphs that returned both a pass and a fail under identical
input*. A gate that accepts on a single-episode delta will accept noise. Minimum
episode counts per accept decision must be set before L3 runs, not after.

---

## 6. Open questions

1. Which third model for the re-record? It must be strong enough that its failures are
   informative and cheap enough to run ~20 episodes × 83 graphs.
2. Should `val.yaml` be per-graph or a registry-level policy? Per-graph is more flexible;
   registry-level is far less to maintain across 83 bundles.
3. Does edge guidance belong on the edge or on the *join*? A node with three incoming
   edges gets three guidance strings; the paper does not address ordering or conflict.
4. How does L2's local subgraph interact with `kind: subgraph` phase boundaries — does a
   child node see edges of its parent phase, or only its own?
