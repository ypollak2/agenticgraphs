# AGR v1.7 — the goal

A graph now knows what it is working on, or refuses to work.

## The gap this closes

`state.inputs` has existed since v1.1 and named, per graph, exactly what the caller
must bring at entry. **Nothing ever supplied it.** `run_graph` opened with `bb = {}`
and had no parameter for entry inputs; no eval case passed any. Meanwhile:

- `validate.py` trusted the declaration — a node's `inputs` lint passes because
  "state.inputs supplies it";
- `compose.py` read it for contract compatibility.

So the linter vouched for values that never arrived. 31 of 83 graphs declared inputs
they never received. `code-review-pipeline` reviewed no particular diff;
`hiring-lifecycle` ran a hiring loop for no particular role. The contracts still
passed, because a model handed an empty board invents a plausible subject and answers
about that — **a well-typed answer to a question nobody asked**, the same failure class
catalogued in [v9](plans/v9-nine-composites.md) and [v10](plans/v10-remaining-sixteen.md).

This is the anti-pattern v1.3 named when it deleted `approval.timeout` and
`retries.backoff` rather than carry them a third version unenforced.

## What v1.7 adds

### `inputs` — the seeding

```python
run_graph(doc, runner, inputs={"goal": "...", "repo": "..."})
```

`bb` starts from `inputs` instead of `{}`. Passing nothing reproduces pre-v1.7
behaviour exactly, which is why the v1 trace lock still holds byte-for-byte.

### `goal` — the declaration

```yaml
goal:
  required: true
  description: the role to fill and what a successful hire must be able to do
state:
  inputs:
  - goal
  - role_brief
```

| field | meaning |
|---|---|
| `required` | the graph will not run without a goal on the blackboard |
| `description` | what the caller must state; shown verbatim when the graph refuses |
| `supplied_by_trigger` | the firing event carries the subject, so `required` applies only to manual invocation |

### The refusal

Checked before anything is scheduled. A graph missing a required goal executes **zero
nodes** and returns a report carrying `goal_missing` — the same shape as `deadlocked`
and `budget_exhausted`, not an exception. `RunReport.passed` is false.

`goal_missing` deliberately does **not** write to `rep.trace`: that field means "nodes
that executed", and callers compare it against node ids.

### Which graphs require one

Derived, not hand-picked: **a graph requires a goal exactly when it declares
`state.inputs`** — that declaration already records that its entry needs something no
node produces. 31 graphs, migrated by
[`scripts/derive_goals.py`](../scripts/derive_goals.py) with **zero asserts modified**.

`self-healing-ci` and `supplier-risk-monitor` declare both `state.inputs` and
`triggers`, so they carry `supplied_by_trigger: true` — required on manual invocation,
exempt on their own schedule. Without that they could never fire.

### Lints

| Lint | Catches |
|---|---|
| `goal.required` with no `goal` in `state.inputs` | a requirement enforced against a key nothing supplies |
| a node declaring a `goal` input with no `goal` block | the v1.4 disconnect, in a new field |
| `goal.required` + `triggers` without `supplied_by_trigger` | a cron graph that could never fire |
| `goal.required` with no `description` | a refusal that cannot say what it wants |

### Surfaces

- `agr goal <graph> "<text>"` — run one graph against a stated goal.
- `agr eval --goal TEXT` — override the goal in every golden case.
- `search_graphs` (MCP) returns `goal_required` and `goal_description`, so an agent
  learns what to bring *before* spending a call on `get_graph` or `instantiate`.
- `/goal` — the slash command in [`.claude/commands/goal.md`](../.claude/commands/goal.md),
  which asks the user for a goal rather than inventing one when the session has none.
- Cards carry a 🎯 **Requires a goal** line above the topology.

## Why v1.7 and not v1.6

`agr/v1.6` is not a free number. `validate._lint_provenance` arms a **hard** provenance
error for graphs declaring exactly `agr/v1.6` — a staged escalation authors opt into one
graph at a time, after reviewing that graph's provenance asserts.

Migrating the registry onto v1.6 for an unrelated reason would have armed that
escalation for 83 unreviewed graphs. `clinical-protocol-lifecycle` would have failed on
`registry_id` — a ground-truth field no binding here can obtain — while the change under
review was about goals. The only ways out would have been weakening an assert or
shipping a red registry.

`registry.SPEC_VERSION` is now the single source of truth, and
`test_no_registry_graph_declares_v16` keeps that gate un-armed until someone arms it
deliberately.

## What this does not establish

Seeding a goal makes contracts **easier to satisfy, not more truthful**. v10 predicted
exactly this for typed scalars and was right: 3 graphs moved, 1 grounded. A model given
a concrete subject writes a more plausible answer about it, and plausibility is not
evidence.

`assert-grounded` therefore stays orthogonal to pass/fail.

**The re-record has now been run, and it could not answer the question.** 31 graphs on
`qwen3-coder:30b` with the goal seeded: 10 improved, **5 regressed**, registry-wide
unsatisfiable 14 → 11. Seeding a goal cannot *break* a passing graph, so the five
regressions were resampled — and two graphs produced both a pass and a fail under
identical input, while three reversed outright. Registry flaky cells went 2 → 4.

A cell that flips on resampling cannot evidence a change between runs. Every
improvement was also recorded with **0 tool calls**. So v1.7 changed what a graph is
*told*, and has not been shown to change what a model *produces* — at one sample per
cell, this design cannot show it. 150 of 158 cells still sit at n=1, and that, not
another feature, is the next measurement. Full analysis:
[v11-goal.md](plans/v11-goal.md#j8--the-re-record-and-what-it-actually-measured).
