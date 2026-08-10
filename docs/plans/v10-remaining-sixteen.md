# Plan — the remaining 16

Measured at `9a8ce75`. 5 composites + 11 primitives that no recorded model satisfies.

## Diagnosis

| class | count | what the failure actually is |
|---|---|---|
| **type error** | 7 | still `AttributeError`/`TypeError` — the key is untyped |
| **claim false** | 9 | checked, evaluated false — no type error at all |
| by construction | **0** | *and that is wrong — see U3* |

### U1 — 7 graphs: my shape derivation only handled comprehensions

`derive_shapes.py` infers `list[{...}]` from `for f in output.findings`. It infers
**nothing** from a bare scalar read:

```
output.criteria_consistent == true      -> untyped
output.unreviewed_ambiguous == 0        -> untyped
output.snapshot_before == output.snapshot_after   -> untyped
```

Seven of the sixteen fail on exactly those. The assert states the type just as
plainly as a comprehension does — `== true` is a bool, `>= 3` is an int — and the
derivation simply never looked.

`framework-migration` types 0 of 14. `feature-delivery-lifecycle` types 1 of 30.

### U2 — 4 graphs: the claim needs a real execution loop

`bug-triage-and-fix` (`test_failed_before_patch and test_passes_after_patch`),
`flaky-test-reflexion` (`consecutive_green >= 3`),
`test-suite-generation` (`coverage_delta > 0`),
`docs-code-sync-audit` (`exit_code == 0`).

Each is satisfiable *in principle* with `run_command` bound — run the test before
the patch, run it after, count consecutive greens. Three of the four do not
declare `run_command` on the node that owes the fact.

`docs-code-sync-audit` already has it and still fails, because the commands
genuinely do not exit 0. **That one is a true finding and stays failing.**

### U3 — 5 graphs: the by-construction detector under-reports

```
output.matches_ownership_map        needs an on-call ownership map
output.matches_validated_set        needs a labelled validation set
output.registry_id is not None      needs a trial registry
all(c.paper and c.section ...)      needs a paper corpus
output.recomputed_effect            needs the raw experiment data
```

None is obtainable here. All five report as *unsatisfiable by model*, because
`PROVENANCE_FIELDS` is a hardcoded list of URL/log/file names and these are
ground-truth **datasets**, not provenance strings.

The category is right and its detector is too narrow. That is a bug in the thing
built one commit ago to prevent exactly this mislabelling.

---

## The work

**U1** — extend `derive_shapes.py` to scalar asserts:
`== true` → `bool` · `>= N`, `> N`, `== N` → `int` · `is not None` → `any` ·
`abs(a - b)` → `float`. Same principle: read the type the contract already states.

**U2** — declare `run_command` on the node owing an execution fact, in the 3 that
lack it. Not loosening anything; the contract always assumed the node could run
something.

**U3** — widen the by-construction detector from a field-name list to a
**capability question**: does any binding here produce this class of fact?
Add a `GROUND_TRUTH_FIELDS` set (`matches_*`, `*_id` against an external
registry, `recomputed_*`) and label those graphs 🔌.

---

## Acceptance criteria

| # | Criterion | Target | Measured by |
|---|---|---|---|
| H1 | type-error failures among the 16 | 7 → **0** | recordings |
| H2 | every scalar assert key is typed | all | shape sweep |
| H3 | the 3 execution graphs declare `run_command` | 3 | lint |
| H4 | 5 ground-truth graphs labelled 🔌 by construction | 5 | `contract-findings.md` |
| H5 | **unsatisfiable-by-model: 16 → ≤8** | ≤8 | re-record |
| H6 | no assert weakened — 0 expressions changed | 0 | HEAD-vs-tree parse |
| H7 | 233+ tests green, `make check` clean | yes | CI |

**H5 is the point.** ≤8 rather than 0 because the 5 ground-truth graphs cannot
move without data this repo does not have, and `docs-code-sync-audit` is a true
failure that *should* stay red.

**H6 is the guard.** `output.criteria_consistent == true` is trivially satisfied by
deleting it. Sixteen graphs is a lot of temptation.

## Risk

The one worth naming: **U1 will make more graphs pass without making them more
truthful.** Typing a scalar tells the model to return `true` rather than prose —
and `true` is exactly as easy to fabricate. The pilot already demonstrated this
(`docs-code-sync-audit` passes with zero tool calls and perfectly-shaped output).

So H5 counts passes, and the **depth column decides what they are worth**. Any
graph that moves to passing without a grounded run is reported as such, not
celebrated.


---

# Outcome — H5 missed, and the predicted risk is what happened

| # | Criterion | Target | Actual | |
|---|---|---|---|---|
| H1 | type-error failures among the 16 → 0 | 0 | **10** (on gpt-4o alone) | ❌ |
| H2 | every scalar assert key typed | all | 116 outputs typed, was 39 | ✅ |
| H3 | execution graphs declare `run_command` | 3 | 2 (the third already had it) | ✅ |
| H4 | ground-truth graphs labelled 🔌 | 5 | 12 detected registry-wide | ✅ |
| H5 | **unsatisfiable-by-model: 16 → ≤8** | ≤8 | **11** | ❌ |
| H6 | no assert weakened | 0 | **0 expressions changed** | ✅ |
| H7 | tests green, `make check` clean | yes | 233 tests | ✅ |

Registry-wide: unsatisfiable **16 → 14**, model-dependent 20 → 23.

## The risk section called it

> *"U1 will make more graphs pass without making them more truthful. Typing a
> scalar tells the model to return `true` rather than prose — and `true` is
> exactly as easy to fabricate."*

Three of the sixteen now pass on `gpt-4o`. **One is grounded.**

| graph | tool calls | what the pass is worth |
|---|---|---|
| `bug-triage-and-fix` | 6, grounded | earned — it ran the test before and after |
| `ab-test-analysis` | **0** | `recomputed_effect` has no data source here |
| `clinical-protocol-lifecycle` | **0** | `registry_id` has no registry here |

Both zero-call passes are already labelled 🔌 *unsatisfiable by construction*.
**They pass by producing a well-typed value for a fact nothing can establish.**

That is not a defeat for the depth column — it is the depth column doing the only
job it has. A registry reporting these three as "3 more passing" would be
reporting two fabrications as progress.

## Why H1 was missed

Typing tells the model what a key *should* be; it does not make the model produce
it. Ten type errors remain because the model omitted the key entirely rather than
returning it with the wrong type — `AttributeError`, not a shape violation. A
shape can only be checked on a value that exists.

The lever that works on a missing fact is a binding, not a type. That is U2, and
it moved exactly the graph it should have (`bug-triage-and-fix`).

## What this run actually establishes

**Typing is necessary and not sufficient, and the evidence now says so with
numbers.** 116 outputs typed moved 3 graphs, of which 1 truthfully. The remaining
11 split cleanly:

- **6** need a binding this repo has but the graph does not use well
  (`framework-migration` needs a filesystem snapshot; `screenplay-coverage`
  recorded 0 tool calls despite having `web_search`)
- **5** are genuine claims that were checked and did not hold —
  `docs-code-sync-audit`'s commands really do not exit 0

**No further work should be spent on typing.** The next honest lever is making
bound tools actually get *used* — `screenplay-coverage` had `web_search`
available and made zero calls, which is a prompting and motif problem, not a
contract one.
