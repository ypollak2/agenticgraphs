# v19 finding — the live scoreboard is substantially measuring empty fixtures

Found while trying to A/B the v1.9 guidance mechanism. It stops that experiment,
and it is a bigger result than the experiment would have been.

## The observation

`alert-noise-reduction` fails `output.dedupe_ratio > 0 and not output.missed_paging_alerts`
identically in 12 of 12 live runs, both arms. Reading the frames says why:

```
case inputs: {"goal": "the last 30 days of paging alerts"}      <- the ONLY input

partition -> {"shards": [{"date_range": "2023-07-01 to 2023-07-31",
                          "paging_alerts_count": 142, "dedupe_ratio": 0.85}, ...]}
map       -> {"shard_result": "map_shard"}          <- its own key name, as a value
reduce    -> {"dedupe_ratio": 0, "missed_paging_alerts": 0}
```

There are no alerts. The case seeds a goal string and nothing else, so `partition`
invents plausible-looking data, `map` returns its own output key as a placeholder
because it has nothing to map over, and `reduce` reports a deduplication ratio of
zero — **correctly**. The model is being honest. The assert demands work on data
the fixture never supplied.

## The causal test

Same graph, same model, same seed. The only variable is whether the case carries data:

| inputs | no guidance | guidance |
|---|---|---|
| goal only | **fail** | **fail** |
| goal + 6 real alerts | **pass** | **pass** |

Seeding data flips the graph from fail to pass with no guidance at all. The failure
was never a guidance problem, a model-quality problem, or a graph-design problem.

## How widespread

| case inputs | graphs | mean live pass_rate |
|---|---|---|
| goal only — nothing to work on | **71** | **0.614** |
| real data seeded | 12 | **0.898** |

71 of 83 graphs are scored on cases that hand them nothing but an instruction. The
28-point gap between the two populations is the size of the measurement artefact.

`case_inputs` seeds `goal` because v1.8 made `goal.required` universal, and nothing
ever required a case to also carry the *subject* of that goal. The 12 graphs that do
carry one (`ownership_map`, `holdout_labels`, `validated_labels`, `threshold`,
`page_limit`) are the ones that score near-ceiling.

## What this invalidates, and what it does not

**Invalidated — the guidance A/B, for now.** The revised 8-graph population from
`v19-guidance-experiment.md` §1.1 is drawn from graphs at live 0.0, and that
population is selected for fixture poverty as much as for anything else. Running the
A/B on it would measure whether prose helps a model work on data it does not have.
The answer to that is already known: it does not. Both pilots returned delta 0.000,
and both are explained by this, not by the mechanism.

**Invalidated — "45 of 83 graphs have live headroom" as a quality claim.** Much of
that headroom is missing fixture data. How much is not yet known, and the honest
statement is that the registry cannot currently separate a graph that a model fails
from a graph the fixtures never let it attempt.

**NOT invalidated — the optimizer fix (556a69b).** Replay-scored gating is sound and
independently valuable: it caught `op_tighten_max_steps` sizing budgets from mock
traces and stalling three graphs. That bug is real regardless of fixture quality.

**NOT invalidated — the v1.9 mechanism itself (8796359).** It is implemented, wired
into both prompt paths, leak-audited, and verified to reach the model and to leave
prompts byte-identical when unused. It is unevaluated, not disproven.

## Prerequisite this creates

Any experiment on agent *quality* — the paper's mechanism, self-evolution, anything
downstream — needs cases that carry a subject, not just an instruction. That is a
fixture-authoring effort across up to 71 graphs and is a scope decision, not
something to absorb silently into a v1.9 experiment.

Suggested order:
1. Add a `data` block convention to `cases.yaml` and thread it through `case_inputs`.
2. Author data for the 8 guidance candidates first — enough to re-run the A/B.
3. Re-record, and re-read the scoreboard. The 0.614 population is the one to watch.
4. Only then re-open the guidance A/B, and only then consider L3.

## Caveat

The 0.614 / 0.898 split is correlational on its own. It is reported as causal here
because the paired test above isolates the variable directly on one graph. Whether
every one of the 71 recovers the way `alert-noise-reduction` did is unmeasured —
that is exactly what step 2 above would find out.
