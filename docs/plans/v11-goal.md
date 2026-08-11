# AGR v1.7 — `goal`: the input a graph must be given before it may run

> Planned as v1.6. Shipped as v1.7 — see "J-numbers" below and
> [agr-v1.7.md](../agr-v1.7.md#why-v17-and-not-v16); v1.6 turned out to be load-bearing.

## Context

Today every graph in this registry starts work without knowing what it is working
*on*. `run_graph` opens with `bb: dict = {}` (`src/agenticgraphs/harness.py:711`)
and has no parameter for entry inputs. No eval case supplies any.

That is not merely a missing feature — it is a **declared-but-unread field**, the
exact anti-pattern this repo has twice named and once deleted over:

- 31 of 83 graphs declare `state.inputs`.
- `validate.py:78,130,193` trusts those declarations: a node's `inputs` lint passes
  because "state.inputs supplies it".
- `compose.py:136` reads them for contract compatibility.
- **The runtime never seeds them.** The linter vouches for a value that never arrives.

So `code-review-pipeline` reviews *no particular diff*, and `hiring-lifecycle` runs a
hiring loop for *no particular role*. The contract asserts still pass, because a model
handed an empty board invents a plausible subject and answers about that. This is the
same failure class as the zero-tool-call passes catalogued in
`docs/plans/v9-nine-composites.md` and `v10-remaining-sixteen.md`: **a well-typed
answer to a question nobody asked.**

**Intended outcome.** A first-class `goal` on every graph — usable by all of them,
*mandatory* on the 31 that cannot know their subject without one. A graph missing a
required goal does not guess: it refuses, visibly, and says what it needs. Plus a
`/goal` slash command so an agent (or you) can invoke a graph by stating a goal in
plain language.

**Decisions taken** (from your answers):
- `required: true` is **derived from `state.inputs` being non-empty** — 31 graphs — not
  hand-picked. Same method as v1.4: derive declarations from what is already there.
- The `state.inputs` seeding fix is **folded in**, because without it `goal` is
  declared-and-unread on day one.

---

## Design

### 1. The `goal` block (spec)

`spec/agr-graph.schema.json` — new top-level property (`additionalProperties: false`
today, so this requires a schema change) and an `apiVersion` bump to `agr/v1.6`:

```yaml
goal:
  required: true
  description: the pull request or diff under review
  # optional, for the 2 trigger+inputs graphs:
  supplied_by_trigger: true
```

- `required: false` is the default, so all 83 graphs keep validating untouched until
  each is migrated.
- `supplied_by_trigger: true` marks `self-healing-ci` and `supplier-risk-monitor`,
  which have **both** `state.inputs` and `triggers` — the firing event is the goal, so
  the requirement applies only to manual invocation.

**Version note to settle before coding:** `docs/plans/v7-agr-1.6.md` already used the
name "v1.6" for harness-only work that never touched the schema (the enum still stops
at `agr/v1.5`). This is the first schema bump since v1.5, so `agr/v1.6` is
structurally correct but collides with that doc's name. Rename the doc or bump to
`agr/v1.8` — flagging rather than silently choosing.

### 2. Seeding — the half that makes it real

`run_graph` gains an `inputs` parameter (`harness.py:658`):

```python
def run_graph(doc, runner, root=None, auto_approve=False,
              run_commands=False, resume_from=None, inputs=None):
    ...
    bb: dict = dict(inputs or {})     # was: bb = {}
```

This single line closes the gap for all 31 graphs already declaring `state.inputs`,
independent of `goal`.

### 3. The refusal

New `RunReport` field alongside `state_violations` (`harness.py:197-217`):

```python
goal_missing: str | None = None      # the graph's goal.description
```

Checked **before** the scheduler loop. When `goal.required` and no `goal` key in
`inputs`: set `goal_missing`, run zero nodes, return. `RunReport.passed`
(`harness.py:272`) gains `and not self.goal_missing`.

This is a refusal, not an exception — it lands in the report like
`deadlocked` and `budget_exhausted` do, so it shows up in evals and the scoreboard
rather than crashing a caller.

### 4. Nodes must actually see it

`_prompt_text` (`harness.py:538`) already serialises the whole blackboard, so a seeded
goal reaches the model for free. Add one explicit line so it is not buried in a JSON
blob — the v1.6/v1.7 lesson was that models ignore facts they must dig for:

```
Your goal for this run: <goal>
```

### 5. Lints (`validate.py`, joining `_lint_v11`'s family)

| Lint | Catches |
|---|---|
| `goal.required` but no `state.inputs` entry named `goal` | a requirement nothing supplies |
| a node's `inputs` names `goal` but graph declares no `goal` block | the v1.4 disconnect, again |
| `goal.required` with `triggers` and no `supplied_by_trigger` | a cron graph that can never fire |
| `goal.description` missing when `required: true` | a refusal that can't say what it wants |

### 6. Surfaces

- **CLI** (`cli.py:34` pattern): `--goal TEXT` on `agr eval`; new
  `agr goal <graph> "<text>"` that seeds and runs one graph.
- **MCP** (`mcp_server.py:32,44`): `search_graphs` and `get_graph` report
  `goal_required` + `description`, so an agent knows what to bring **before** calling
  `instantiate`.
- **`/goal` slash command** — `.claude/commands/goal.md`, committed to the repo:
  resolve a graph from the stated goal via `search_graphs`, read its goal
  requirement, and if the session context carries no relevant request, **ask the user
  for one rather than inventing it.** This is the piece you asked for by name.
- **Cards** (`scripts/gen_cards.py:136`): a "Requires a goal" row in the header table,
  regenerated via `make regen`.

### 7. Migration of the 31

Derived, not hand-written: a script reads each graph with non-empty `state.inputs`,
adds `goal: {required: true, description: ...}`, and appends `goal` to `state.inputs`.
Descriptions are seeded from the graph's existing `description` field and reviewed —
the same derive-then-review loop v1.4 used, which is why it changed zero asserts.

Their eval cases (`evals/<name>/cases.yaml`) each gain a `goal:` line. **This is where
the work is** — 31 case files, and they go red until it lands.

---

## Acceptance criteria

| # | Criterion | Target | Measured by |
|---|---|---|---|
| J1 | `state.inputs` reaches the blackboard | all 31 | new harness test |
| J2 | the 31 declare `goal.required: true` | 31 | schema sweep |
| J3 | a required goal, absent → 0 nodes run, `passed` false | always | harness test |
| J4 | the 4 lints catch their cases | 4 | unit tests |
| J5 | `/goal` asks rather than invents when context has no goal | yes | command text + manual run |
| J6 | **no assert weakened — 0 expressions changed** | 0 | HEAD-vs-tree parse |
| J7 | 234 existing tests green, `make check` clean | yes | CI |
| J8 | re-record: does seeding move any of the 14 unsatisfiable? | reported | recordings |

**J6 is the guard**, per repo convention. Seeding a goal makes contracts *easier* to
satisfy; the temptation to also relax an assert must show as zero changed expressions.

**J8 is the honest question.** I am not predicting it moves any. It is measured and
reported either way.

---

## Risk

**The v10 risk, restated, because it applies exactly.** v10 predicted that typing
scalars would make graphs pass without making them truthful — and it did: 3 moved, 1
grounded. Seeding a goal carries the same shape. A model given a concrete subject
writes a more plausible answer about it, and plausibility is not evidence.

Mitigation is the one already built: `assert-grounded` stays orthogonal to pass/fail,
and J8 reports any newly-passing graph with its tool-call count, so a pass earned by a
real tool call is distinguishable from a better-informed fabrication.

**Second risk: 31 graphs become refusers.** Every one of their eval cases goes red
until it carries a goal. That is intended and visible, not a regression — but it means
this lands as one commit or a red main.

---

## Verification

```bash
uv run --all-extras agr validate                      # schema + all 4 new lints
uv run --all-extras pytest -q                         # 234 existing + new
uv run --all-extras agr eval code-review-pipeline     # expect: refuses, no goal
uv run --all-extras agr goal code-review-pipeline "review PR #42 for auth changes"
uv run --all-extras python scripts/gen_cards.py && make check   # cards not stale
```

End-to-end: `agr mcp`, call `search_graphs("hiring")`, confirm the result carries
`goal_required: true` and a description before `instantiate` is reachable. Then
`/goal review the auth diff` in a session with no prior context — it must ask.

---

## Files

| File | Change |
|---|---|
| `spec/agr-graph.schema.json` | `goal` block, `apiVersion` enum → `agr/v1.6` |
| `src/agenticgraphs/harness.py` | `inputs` param, `bb` seeding, `goal_missing`, `passed`, prompt line |
| `src/agenticgraphs/validate.py` | 4 lints + v1.6 feature gate |
| `src/agenticgraphs/evalcmd.py` | thread `goal` from cases into `run_graph` |
| `src/agenticgraphs/cli.py` | `--goal`, `agr goal` |
| `src/agenticgraphs/mcp_server.py` | expose `goal_required` |
| `scripts/gen_cards.py` | header row |
| `.claude/commands/goal.md` | **new** — the `/goal` command |
| `graphs/**/graph.yaml` | 31 gain `goal:`; pattern identical across all |
| `evals/**/cases.yaml` | 31 gain `goal:` |
| `docs/agr-v1.6.md`, `docs/plans/v11-goal.md` | spec + this plan, repo convention |
| `tests/test_goal.py` | **new** — J1–J4 |

---

# Outcome

| # | Criterion | Target | Actual | |
|---|---|---|---|---|
| J1 | `state.inputs` reaches the blackboard | all 31 | seeded via `run_graph(inputs=)`; 3 tests | ✅ |
| J2 | the 31 declare `goal.required: true` | 31 | 31, derived from `state.inputs` | ✅ |
| J3 | a required goal, absent → 0 nodes run, `passed` false | always | 6 tests incl. trigger exemption | ✅ |
| J4 | the 4 lints catch their cases | 4 | 4 + the apiVersion gate, parametrized | ✅ |
| J5 | `/goal` asks rather than invents when context has no goal | yes | `.claude/commands/goal.md` step 2 | ✅ |
| J6 | **no assert weakened — 0 expressions changed** | 0 | **0 of 118**, parsed before/after | ✅ |
| J7 | tests green, `make check` clean | yes | **251 passed**, 1 xfailed | ⚠️ |
| J8 | re-record: does seeding move any of the 14 unsatisfiable? | reported | **run — the answer is "cannot tell, and here is why"** | ✅ |

**J7 is ⚠️, not ✅.** `pytest` and `agr validate` are green and `make regen` is
idempotent, but `make check`'s `clean-check` step diffs generated docs against the
*committed* tree, so it cannot pass until this lands as a commit. Nothing is being
claimed about it beyond that.

# J8 — the re-record, and what it actually measured

31 graphs re-recorded on `qwen3-coder:30b` with the goal seeded. Conditions matched
the baseline exactly: same model, same graphs, **no tools** — all 83 prior recordings
carry 0 tool calls, so binding them would have changed two variables at once.

| | |
|---|---|
| improved (0.0 -> 1.0) | 10 |
| regressed (1.0 -> 0.0) | 5 |
| unchanged | 16 |
| registry-wide unsatisfiable | 14 -> 11 |

**And none of that is attributable to the goal.**

## The regressions were the tell

Seeding a goal has no mechanism for *breaking* a graph that passed. Five did. So the
five were re-recorded twice more, identical inputs:

| graph | sample A | sample B | |
|---|---|---|---|
| `architecture-decision-tournament` | PASS | PASS | the regression was noise |
| `book-editing-pipeline` | PASS | PASS | the regression was noise |
| `onboarding-plan-builder` | PASS | **FAIL** | **coin flip** |
| `red-team-blue-team-hardening` | PASS | **FAIL** | **coin flip** |
| `invoice-reconciliation` | FAIL | FAIL | consistently failing |

Two graphs produced both a pass and a fail **under identical input, same model, same
session**. Three of the five "regressions" reversed on a resample.

If a cell can flip on resampling, then a cell that flipped from 0.0 to 1.0 between the
baseline and this run is not evidence that anything changed. The 10 improvements and
the 5 regressions are the same phenomenon, and the goal is not it. Registry flaky cells
went 2 -> 4 as a direct result of looking.

## Not one improvement was grounded

All 83 `qwen3-coder:30b` recordings contain **0 tool calls**. The first pass of this
analysis printed `assert-grounded` against five of the improved graphs; that depth is a
per-graph aggregate that includes `gpt-4o` recordings, 12 of which do carry tool calls.
It was not a property of this run. Every improvement here is a model asserting.

That is the v10 finding restated by a different route: a better-informed model writes a
more plausible answer, and plausibility is not evidence.

## What this establishes

**Seeding a goal changed what the graph is told. It has not been shown to change what
the model produces, and at n=1 per cell this design cannot show it.** The registry's
own known limit — "each cell is one sample" — is not a footnote here, it is the whole
result. The honest reading of 14 -> 11 is that three graphs passed once, ungrounded,
in a cell demonstrated to be unstable.

The measurement that would settle it is repeated samples per cell, not another feature.
`AGR_SAMPLES` already exists and 150 of 158 cells still sit at one sample.

## What the plan did not anticipate

**`agr/v1.6` was already load-bearing.** `_lint_provenance` arms a hard provenance error
for graphs declaring exactly v1.6 — a per-graph opt-in. The plan flagged v1.6 as a
*naming* collision with `docs/plans/v7-agr-1.6.md` and recommended it anyway. It was a
*semantic* collision: migrating 83 graphs onto v1.6 armed an unrelated stricter lint,
and `clinical-protocol-lifecycle` failed on `registry_id`, a ground-truth field no
binding here can obtain.

The two ways to make that green were weakening an assert (violating J6) or shipping a
red registry. The third way — the one taken — was to stop reusing the number. The
detection came from the test suite, not from review: the plan's own version note said
"flagging rather than silently choosing", and then chose the flagged option.

`registry.SPEC_VERSION` is now one source of truth, and
`test_no_registry_graph_declares_v16` keeps the gate un-armed until it is armed on
purpose.

**Two of my own changes were caught by existing tests, not by me.**

- The refusal wrote `"refused: no goal — ..."` into `rep.trace`. `trace` means "nodes
  that executed" and the adapter-parity test compares it against compiled node ids. The
  reason now lives only on `goal_missing`.
- `subgraphs.expand` hardcoded `apiVersion: agr/v1.2` on expanded composites. Its own
  comment called that "the version whose surface it actually uses" — a floor. A
  preserved `goal` block raises the floor, so a v1.2 stamp produced a doc contradicting
  its own contents.

**Two version-completeness tests had hardcoded numbers** (`!= "agr/v1.5"`,
`not in ("agr/v1.4", "agr/v1.5")`). They exist to catch an incomplete migration and had
to be edited by every migration they were meant to guard. Both now read `SPEC_VERSION`.
