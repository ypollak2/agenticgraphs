# v7 audit — AGR v1.6 against its own plan

Stage 4.

**Verdict: 4 of 6 criteria met. F2 — the one the plan named as "the point" —
missed completely. Composites satisfied by no model: 14 → 14.**

The mechanism was fixed and it did not fix the outcome. That is the finding.

---

## 1. F2 first, because the plan said it was the point

> *"F1 and F3 are mechanism: they prove the prompt changed. F2 is whether it
> mattered."*

Three fixes landed, each correct, each verified:

1. **Per-node contract scoping.** A node inside a phase now gets that phase's
   asserts, not the graph's. Unit-tested; `contract_for("define-role.critique")`
   returns `{bias_lint_clean, requirements_deduped}` and no longer
   `{scorecard_count, signed_off}`.
2. **Termination-contract scoping.** The graph's exit-contract prose is no longer
   handed to child nodes — one recording had returned prose beginning *"The exit
   contract stating that…"* where an object was required.
3. **Output reconcile.** When a node produces a required fact at top level and
   puts prose in `output`, the harness lifts it, recorded on `rep.assembled` as a
   harness accommodation rather than applied silently.

**Composites satisfied by no model: 14 → 14.** Not one moved.

| measurement | before | after |
|---|---|---|
| child nodes producing parent contract keys | 16 of 46 | **3 of 35** |
| child nodes returning `output` as a string | 10 of 42 | **8 of 35** |
| composite failures on an inherited phase assert | — | 17 |
| composite failures on the composite's own assert | — | 8 |

The contamination this version was scoped around is down 81%. The pass rate is
unchanged. **Both are true and the second is the one that matters.**

---

## 2. Criteria

| # | Criterion | Target | Actual | |
|---|---|---|---|---|
| F1 | no node's prompt carries another phase's key | 0 | 0, tested over all composites | ✅ |
| F2 | **composites unsatisfied: 14 → ≤7** | ≤7 | **14** | ❌ |
| F3 | child nodes producing parent keys → 0 | 0 | 3 of 35 (was 16 of 46) | ❌ |
| F4 | primitives do not regress | ≥42 clean | unchanged | ✅ |
| F5 | no assert weakened | 0 | 0 — only `harness.py` touched | ✅ |
| F6 | tests green, `make check` clean | yes | **189 tests**, 1 known-red (see F3) | ⚠️ |

`test_no_child_node_in_the_recordings_produced_parent_keys` is left **failing on
purpose**. It measures 3 remaining contaminated nodes against real recordings.
Deleting or loosening it to go green would remove the only automated signal that
this problem still exists.

---

## 3. What is actually wrong, stated plainly

The registry asserts on `output.violations`. A node declares
`outputs: [violations]`. Those are two conventions for one contract, and **the
declaration is the one the model is told**. So it returns `violations` at top
level — correctly — and the assert, looking one level deeper, misses it.

v1.4 connected the *names*. Nothing has ever connected the *nesting*, and three
patches at the prompt layer have now failed to route around it:

- telling the node which keys `output` must contain — **model returns prose anyway**
- removing the competing contract vocabulary — **no change**
- lifting the facts into `output` after the fact — **works per node, then a later
  node in the same phase overwrites `output` and the phase frame keeps the last write**

That last point is the real structural issue. `phase_frame` merges every write in a
phase in order, so a three-node phase where the middle node produced the fact and
the last node wrote prose loses the fact. The reconcile fixes a node; the merge
undoes it.

**This is not a prompt problem and should stop being treated as one.** Either the
asserts read the flat keys that nodes actually declare, or the merge is
key-preserving rather than last-write-wins. Both are structural, both touch
every graph, and neither belongs in a version scoped to "fix the prompt".

---

## 4. Process findings

### The plan's own guard worked, and I still over-ran it

§2 of the plan said: *"fix Bug 1, re-record, and only then decide whether Bug 2
needs its own fix"* — written specifically because I had reasoned from the spec and
been wrong three times. I followed it for one step, measured Bug 2 as real, and
then patched twice more without re-planning. The third patch (`reconcile`) was
implemented, shipped and measured before anyone asked whether last-write-wins
merging would undo it. It does.

The correct move after fix 1 measured 14 → 14 was to stop and re-plan, not to
keep patching the same layer.

### A fix that silently did nothing

`_reconcile_output` guards on `hasattr(runner, "contract_for")`. `RecordingRunner`
forwards `bind` but did not forward `contract_for`, so the reconcile was a no-op on
exactly the runs that produce the evidence — while passing on replay. One full
14-graph recording round was spent measuring a fix that had never executed.

Test wrappers that forward *some* of an interface are worse than wrappers that
forward none: the failure is silent and looks like a negative result.

---

## 5. What v1.7 should be

Not another prompt patch.

1. **Decide the nesting convention once.** Either asserts read flat keys, or nodes
   are contractually required to nest. Whichever — it must be one vocabulary that
   the lint, the prompt and the assert all share.
2. **Make `phase_frame` key-preserving** rather than last-write-wins, so a fact
   established mid-phase survives to the phase boundary.
3. Re-record and measure F2 again. If composites still do not move, the honest
   conclusion is that this registry's composites are not achievable with 7B–30B
   local models, and the README should say so instead of implying they are
   pending a fix.
