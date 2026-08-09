# v5 audit — AGR v1.4 against its own plan

Stage 4 of 7.

**Verdict: 6 of 7 criteria met. D4 — the one the plan named as "the point" — was
missed as written: 2 of 4 on `qwen3-coder:30b`, not 3.**

The substantive result is better than that number and must not be used to hide it:
**contracts satisfied by no model went from 4 to 1.**

---

## 1. D4 first, because the plan said it was the point

The plan's own words: *"D1–D3 are mechanism. If the four still fail, v1.4 has
diagnosed better and fixed nothing, and the audit must lead with that."*

| Graph | v1.3 (any model) | v1.4 (any model) | v1.4 on `qwen3-coder:30b` |
|---|---|---|---|
| `earnings-call-digest` | ❌ | **✅** | ✅ |
| `benchmark-driven-optimization-search` | ❌ | **✅** | ✅ |
| `differential-diagnosis-ensemble` | ❌ | **✅** (7b only) | ❌ |
| `ab-test-analysis` | ❌ | ❌ | ❌ |

**D4 as written — ≥3 of 4 on `qwen3-coder:30b` — is missed. 2 of 4.**

**D4's intent — contracts that no model could satisfy — went 4 → 1.**

Both are true. The criterion was stated in terms of one model because that was the
strongest model available, and it turned out that `differential-diagnosis-ensemble`
is satisfied by the 7B model and not the 30B one. That is a real result about
sampling variance, not a technicality to file the criterion under.

### Why `ab-test-analysis` still fails

It is the only one where the assert compares **two facts produced by different
nodes**:

```yaml
assert: "abs(output.recomputed_effect - output.claimed_effect) < 0.01"
```

`claimed_effect` is read from the input by `intake`; `recomputed_effect` is
computed by the analysis step. Every model produced one and left the other `None`.
Declaring both — which v1.4 did, on the right nodes — tells each node what it
owes, but nothing tells the **assembler** that both must be present *simultaneously*
before the assert can mean anything.

That is the next layer down, and it is a genuinely different problem from the one
v1.4 set out to solve: v1.3 was "the contract is not stated", v1.4 is "the contract
is stated per node", and this is "the contract has a *joint* precondition that no
single node owns". Recorded as the v1.5 item rather than patched over.

---

## 2. Acceptance criteria

| # | Criterion | Target | Actual | |
|---|---|---|---|---|
| D1 | unmet verification keys 123 → 0 | 0 | **0** | ✅ |
| D2 | all 83 graphs at `agr/v1.4`, lint clean | 83 | 83, 0 errors, 0 advisories | ✅ |
| D3 | lint catches a synthetic disconnect | yes | test asserts the exact message | ✅ |
| D4 | ≥3 of 4 🚫 contracts pass on `qwen3-coder:30b` | 3 | **2** | ❌ |
| D5 | live pass rate improves vs the v1.3 baseline | improve | 4 🚫 → 1 🚫; 16 → 19 model-dependent | ✅ |
| D6 | no assert weakened | 0 changed | **0 assert expressions changed** (verified by parsing HEAD vs working tree) | ✅ |
| D7 | trace locks hold, tests green, `make check` clean | yes | **165 tests** | ✅ |

---

## 3. Findings

### F1 — My own escape hatch hid the worst case (fixed)

`unconnected_keys` began with:

```python
if not produced:
    return set()   # "a node that declares nothing makes no promise to break"
```

That excused exactly the graphs that needed catching most.
`code-review-pipeline` asserts on `output.verdict` and declared **no outputs at
all** — so it read as fully connected and was promoted to `agr/v1.4` while being
the maximal instance of the gap. Declaring nothing is not a defence; it is the
strongest form of the problem.

Removed. The rationale that produced it is preserved in the code comment, because
it is the kind of reasonable-sounding exemption worth recognising again.

### F2 — Warnings in the error channel bricked mutation (fixed)

The D4 strict/warn split emitted advisories into the same list `lint_graph`
returns. Every caller treats that list as fatal, so `agr infuse` began refusing
every graph with `infusion rejected by gate: warn: ...`.

A "non-blocking warning" that flows through a blocking channel is not a warning.
Advisories now live in `lint_advisories()`, and a test asserts they never appear
in the error channel.

### F3 — A test suite that reverted the migration on every run (fixed)

`tests/test_mutate.py` restored its two mutated graphs with
`git checkout -- <dir>` — i.e. from **HEAD**, not from a snapshot. Every full test
run silently discarded the uncommitted v1.4 declarations on
`code-review-pipeline` and `cost-routed-research`, and the loss looked like a bug
in the migration script. Roughly forty minutes went into chasing it.

Replaced with a working-tree snapshot. Notably these are the same two graphs whose
stale `profile.json` broke CI in v1.1 — being the mutation-test targets makes them
a persistent blind spot, which is now written down.

### F4 — Three compose tests asserted behaviour v1.4 deliberately removed

They exercised the heuristic contract path via registry graphs. Since every graph
declares I/O, that path is unreachable from the registry — the tests were correct
and their premise expired. Rewritten to build the undeclared shape directly, so the
fallback stays covered for graphs authored outside this repo, plus a new test
asserting the pair that previously needed a guess now composes on declared
contracts.

### F5 — `kind: search` crashes on a non-numeric score (open)

`benchmark-driven-optimization-search` errored with
`TypeError: '<' not supported between instances of 'int' and 'str'`. `_search`
sorts candidate scores without checking they are comparable, so a model returning
a string score takes down the run instead of being dropped like an unscoreable
candidate already is.

### F6 — The registry now has no undeclared graph to test against

Every one of the 83 declares its I/O, which is the goal — and it means the
heuristic fallback in `compose` has no real-world exercise left. It is covered by
synthetic tests only. Worth knowing before someone deletes it as dead code.

---

## 4. Stage 5 work list

1. **F5** — guard `_search` against incomparable scores; drop them as unscoreable.
2. Record the D4 miss and the `ab-test-analysis` diagnosis in the README rather
   than reporting "4 → 1" alone.
3. Carry the joint-precondition problem forward as the v1.5 item.
