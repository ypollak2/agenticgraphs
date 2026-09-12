# AGR v1.9 — the subject

A case now supplies what its goal names, and the Live column measures the graph
instead of the model's imagination.

## The gap this closes

v1.7 gave a graph its subject. v1.8 gave it a rubric to judge that subject by.
Neither ever required the *case* to hand the graph anything to work on.

`alert-noise-reduction` is asked to deduplicate the last 30 days of paging alerts.
It was handed `{"goal": "the last 30 days of paging alerts"}` and nothing else. So
`partition` invented plausible shards, `map` returned the literal string
`"map_shard"` — its own output key as a placeholder, because there was nothing to
map over — and `reduce` honestly reported a deduplication ratio of zero. The assert
then failed the graph.

**71 of 83 graphs were scored this way.**

| case inputs | graphs | mean live pass_rate |
|---|---|---|
| goal only | 71 | 0.614 |
| real data seeded | 12 | 0.898 |

A paired run isolates it — same graph, same model, same seed, varying only whether
the case carries data:

| inputs | no guidance | guidance |
|---|---|---|
| goal only | fail | fail |
| goal + 6 real alerts | **pass** | **pass** |

The pattern is the registry's oldest one, one layer below where
[`evidence-history.md`](evidence-history.md) last found it: **anything optional in
the spec ends up unused, and anything unused ends up load-bearing by accident.**
v1.8 made `goal.required` universal. Nothing ever required a case to carry the
subject of that goal.

Worse, **34 graphs already declared the input they needed** — `invoices`,
`manuscript`, `screenplay`, `alert`, `patient_records`, `role_brief`, `incident`,
`repo`, `decision` and 25 more sat in `state.inputs`, and no case ever supplied one.
The mechanism to fix this has existed since `case_inputs` did. The 12 graphs already
scoring 0.898 were using it.

## What v1.9 adds

### Every case carries its subject

All 83 graphs seed real data; 0 remain on goal-only cases. `state.inputs` was
extended on ~40 graphs to declare what their cases now supply. **No schema change
was required** — `case_inputs` has threaded `case.inputs` onto the entry blackboard
since the field existed.

### Edge-carried guidance — shipped, and measured at zero

Edges may carry `guidance`, `condition` and `pitfalls`; `_guidance_for` renders the
prose on a node's *incoming* edges into its prompt. This is the representation and
delivery halves of [arXiv 2609.09153](research/2609.09153-procedural-graphs.md),
with the paper's second LLM call deliberately replaced by static serialization —
their own efficiency ablation found the win is localization, not generation.

**It did not work.** Pre-registered A/B, 8 graphs, 3 paired episodes per arm, 0
leaks: mean delta **−0.125**, **0 of 8 graphs improved**, 1 regression. Full result
in [`plans/v19-guidance-experiment.md`](plans/v19-guidance-experiment.md).

The regression is the useful part. `bug-triage-and-fix` went 6/6 to 0/6 because the
guidance narrated a sequence — *"record what the check returned before you change
anything, then make the fix"* — that the node's declared outputs `exit_before` and
`exit_after` already encode. The prose restated it in a weaker notation and the
model swapped them. **Procedural prose competes with a contract that already
expresses the procedure**, and AGR nodes have declared typed outputs since v1.1 and
carried `criteria` since v1.8. The channel the paper adds was largely occupied.

The fields stay because they cost nothing unused: a graph declaring no guidance
renders a byte-identical prompt. They are implemented and unevaluated-positive, not
recommended.

### The optimizer gate became real

`agr optimize` gated every mutation on canned fixture replay, which all 83 graphs
score 1.0 on — it was hill-climbing a constant. It now scores candidates against
replayed real-model runs. That immediately caught `op_tighten_max_steps` sizing
budgets from mock traces: `performance-optimization` mocks in 5 steps and replays in
11, so a budget of 10 stalled all 8 of its recorded episodes. Three graphs were
being strangled.

## What this costs

**Every recording is retired.** A recording is a measurement, and a measurement is
only valid under the conditions it was taken. All 549 were taken against goal-only
cases, so they measured a model inventing its inputs. The Live column is empty until
a re-record on v1.9 — the honest figure is zero rather than a smaller one, the same
call v1.8 made for the same kind of reason.

## Known limits

- The seeded fixtures are authored, not drawn from the domain. A graph passing on
  data written to fit its contract is weaker evidence than one passing on real data.
- The guidance result is one model (`qwen3-coder:30b`) at one size. Nothing is
  claimed about frontier models.
- The version gates in `validate.py` compare `apiVersion` as strings
  (`< "agr/v1.8"`). Correct through v1.9; will misorder at v1.10.
