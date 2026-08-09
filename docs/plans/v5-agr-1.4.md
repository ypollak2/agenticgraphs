# v5 — "Connect the contracts" (AGR v1.4)

Stage 1 of 7. The single item carried out of the [v1.3 audit](v4-audit.md).

**The gap, measured:** of 183 keys the registry's `verification` asserts read,
**123 (67%) are produced by no declared node output.** 73 of 83 graphs are
affected — including 81 graphs that *do* declare outputs, just not the ones their
own contract checks.

```
verification keys across registry: 183
keys no node declares:            123      <- the gap
graphs affected:                   73 of 83
```

**Goal:** make a graph's verification contract and its node I/O contracts refer to
the same things, and prove it by getting the four contracts no model can satisfy
to pass.

---

## 1. Why v1.3's fix failed, precisely

v1.3 diagnosed the four 🚫 contracts as "the model isn't told which keys it owes",
declared those keys on the **terminal** node, and re-recorded. **0 of 12 runs
passed.**

The reason is a shape problem, not a wording problem:

```yaml
# ab-test-analysis, after v1.3's attempted fix
- id: verify
  outputs: [claimed_effect, recomputed_effect, output]   # terminal declares them
verification:
  - assert: "abs(output.recomputed_effect - output.claimed_effect) < 0.01"
```

`claimed_effect` is established by **intake** (it reads the claim). `recomputed_effect`
is established by the **analysis** step (it does the arithmetic). The terminal node
assembles `output` — it does not compute either number. Declaring both on the
terminal asks one node to report facts it never had, so a model dutifully returns
an `output` object populated with whatever it can see, which is nothing.

**The fix is to declare each fact on the node that establishes it, and tell the
terminal to assemble `output` from the blackboard rather than invent it.**

---

## 2. Design decisions

### D1 — A lint that connects the two contracts

The core deliverable. `lint_graph` gains:

> `lint: verification asserts on 'recomputed_effect' which no node declares as an
> output and state.inputs does not supply`

Keys are extracted from asserts by AST, not regex: `output.<attr>` accesses plus
free bare names, excluding comprehension-bound variables, level literals and
builtins. (The regex version counted `f`, `v` and `for` as blackboard keys — the
kind of near-miss that makes a bad number look like a finding.)

This is the rule that would have caught all four 🚫 contracts at author time, and
the 123-key gap that hid them.

### D2 — Declarations derived from golden fixtures, not guessed

73 graphs need declarations added. Which node produces which key is not guessable
from the YAML — but it is *recorded*: every graph has a golden case naming, per
node, exactly what that node emits.

`scripts/derive_outputs.py` reads `evals/<graph>/cases.yaml` and declares each
key on the node whose fixture emits it. Mechanical, and grounded in the same
artifact `agr eval` already trusts.

*Where a key appears only nested inside a terminal's `output: {...}`,* it is
declared on the terminal — that case is genuine, and D3 handles telling the model
what to do with it.

### D3 — The terminal is told to *assemble*, not invent

`LLMRunner` currently says "You MUST return exactly these keys". For a node whose
declared outputs include `output`, that is the wrong instruction — the object's
contents come from upstream. It gains a second sentence naming the asserted keys
and telling the node to populate them **from the blackboard**, which it can see.

Consumer-in-the-same-version rule (v1.3): this ships with a re-record proving it.

### D4 — Fail the lint, but only for graphs that opt in

Turning D1 on across 73 graphs at once would make `agr validate` red until every
declaration lands. Instead:

- graphs at `apiVersion: agr/v1.4` are **linted strictly** (unmet key = error);
- earlier graphs get the same finding as a **counted warning**, surfaced in the
  scoreboard as a `contract-connected: no` marker.

Migration is then visible and monotonic rather than a flag day. Every graph is
expected to reach v1.4 in this version — the escape hatch exists so partial
progress is honest, not so it can be skipped.

### D5 — Success is measured on the four, not on the lint

A lint that fires is not proof of a fix. The acceptance test is whether
`ab-test-analysis`, `earnings-call-digest`,
`differential-diagnosis-ensemble` and `benchmark-driven-optimization-search`
pass against a real model after the declarations land.

**If they still fail, the diagnosis is wrong again and the audit says so** — as
v1.3's did, rather than reporting the lint as the deliverable.

---

## 3. Schema diff

Small, because the problem is not missing surface:

```jsonc
"apiVersion": { "enum": [..., "agr/v1.4"] }
```

That is all. v1.4 is a *lint* and a *migration*, not new machinery — the fields
needed to express the contract have existed since v1.1 and simply were not used.

---

## 4. Work breakdown

| # | Change | Est. |
|---|---|---|
| 1 | AST key extractor (`validate.asserted_keys`), shared with `compose` | 3h |
| 2 | D1 lint + D4 strict/warn split | 3h |
| 3 | `scripts/derive_outputs.py` — declarations from golden fixtures | 4h |
| 4 | Migrate all 83 graphs; hand-check the ~10 the script cannot resolve | 6h |
| 5 | D3 `LLMRunner` assemble-instruction | 2h |
| 6 | Re-record the 4 🚫 graphs × 3 models; re-sweep the 27 recorded | 4h |
| 7 | Scoreboard `contract-connected` column; tests; docs | 6h |

**≈28h** — the smallest version so far, because it adds almost nothing and mostly
makes existing fields tell the truth.

---

## 5. Acceptance criteria

Applying v1.3's rule: each falsifiable by something other than a fixture.

| # | Criterion | Falsified by |
|---|---|---|
| D1 | Unmet verification keys drop from 123 to 0 | the measurement script |
| D2 | All 83 graphs declare `apiVersion: agr/v1.4` and lint strictly clean | `agr validate` |
| D3 | The lint catches a synthetic disconnect | a test asserting the exact message |
| D4 | ≥3 of the 4 🚫 contracts pass on `qwen3-coder:30b` | recordings |
| D5 | Registry-wide live pass rate improves against the v1.3 baseline (19/25 on the best model) | scoreboard |
| D6 | No assert weakened: every `verification[].assert` string is unchanged | `git diff` on the assert lines |
| D7 | Trace locks hold; 157+ tests green; `make check` clean | CI |

**D6 is the guard.** The cheap way to make 123 unmet keys disappear is to delete
the asserts that reference them. The diff must show declarations added and **not
one assert changed**.

**D4 is the point.** D1–D3 are mechanism. If the four still fail, v1.4 has
diagnosed better and fixed nothing, and the audit must lead with that.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Deriving from fixtures bakes in whatever the fixture author assumed | fixtures are already what `agr eval` trusts; D4 tests against a *real model*, which the fixture cannot influence |
| 123 keys is large enough to tempt a bulk assert-rewrite | D6 diffs the assert strings; any change must be argued in the audit |
| The four still fail | acceptable and reportable — but the audit leads with it, and v1.5 gets a sharper diagnosis, not a quieter one |
| Strict/warn split becomes permanent | every graph is migrated in this version; the warn path is for the migration, not the destination |

---

**Next stage:** v5.2 — implement, starting with the extractor and lint, because the
lint is what tells the migration when it is done.
