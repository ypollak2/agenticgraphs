# v7 — "Each node hears its own contract" (AGR v1.6)

Stage 1. Scope: two bugs found by reading the composite recordings, no new schema.

## 0. The evidence

All 83 graphs recorded on `qwen3-coder:30b`: **42 satisfied, 27 satisfied by no
model — and 14 of those 27 are every single composite in the registry.**

| shape | satisfied by no model |
|---|---|
| primitive | 11 of 65 |
| human-gated | 2 of 4 |
| **composite** | **14 of 14** |

11 of the 14 fail on exactly **one inherited phase assert and none of their own**.
So the composite's own contract is fine; the child's is not.

`hiring-lifecycle`, node `define-role.critique` — a node *inside* the JD-drafting
phase:

```jsonc
{
  "bias_lint_clean": true,                                  // its own key, FLAT
  "requirements_deduped": ["output.scorecard_count >= 3",   // the PARENT's assert
                          "output.signed_off == true"],     //   STRINGS, as a value
  "output": {"scorecard_count": 3, "signed_off": true}      // the PARENT's contract
}
```

---

## 1. Bug 1 — every node is handed the whole graph's contract

`LLMRunner.bind(doc)` collects `self.checks` and `self.asserted` from the expanded
parent and hands the same set to **every** node. A child node inside a phase is
therefore told to produce the parent graph's final answer.

**16 of 46 child nodes across the recordings produced parent-contract keys.** Only
composites have child nodes, which is exactly why this lands on 14 of 14 composites
and mostly spares primitives.

It also explains the short traces: `invoice-reconciliation` ran 3 steps of a
4-phase graph, `hiring-lifecycle` stopped before its gate. Downstream guards read
keys a contaminated upstream node never produced, so the edges never fired. **The
early exit is a symptom, not a separate bug.**

### Fix

`bind` keeps the doc; the per-node contract is computed at `run` time:

- a node `<phase>.<child>` gets the verification entries tagged `phase: <phase>`;
- an untagged node gets the untagged entries;
- if that leaves nothing, the node gets **no** contract text rather than the
  graph's — silence is better than a misleading instruction.

## 2. Bug 2 — declaration and assertion disagree about nesting

```
declared:     outputs: [bias_lint_clean, jd, output, requirements_deduped]
model gave:   {"bias_lint_clean": true, ...}     flat, exactly as declared
assert reads: output.bias_lint_clean             one level deeper
```

The model was right and the assert missed it. v1.4 connected the *names*;
nothing ever connected the *nesting*. Fixtures hid it for five versions by
hand-nesting values under `output`, so the runtime never had to agree with the
assert about where a value lives.

### Fix — and a hypothesis to test, not assume

The assembly hint already says *"The `output` object must contain: […]"*. It fired
here — with the **parent's** keys — and the model partially obeyed, nesting those
and leaving its own flat.

**Hypothesis: Bug 2 is a consequence of Bug 1.** With the hint naming the node's
*own* asserted keys, the model should nest the right ones.

This has to be measured, not assumed. I have reasoned from the spec and been wrong
three times this session (prose asserts, joint preconditions, "0 unsatisfiable").
So: fix Bug 1, re-record, and **only then** decide whether Bug 2 needs its own fix.

If it does, the fallback is a runtime reconcile — after a node runs, lift any
declared key that the contract references as `output.X` into `output` — flagged in
the report as a harness accommodation rather than a model success.

---

## 3. Tests

Written to fail against today's code.

| Test | Asserts |
|---|---|
| `test_a_child_node_is_told_only_its_phase_contract` | `contract_for("define-role.critique")` contains `bias_lint_clean`, **not** `scorecard_count` |
| `test_a_parent_node_is_told_only_the_untagged_contract` | `contract_for("offer")` contains `scorecard_count`, not the phase's keys |
| `test_a_node_with_no_matching_contract_is_told_nothing` | empty, rather than falling back to the graph's |
| `test_a_primitive_graph_is_unaffected` | every node still gets the graph's asserts — no phases, no change |
| `test_the_prompt_never_carries_another_phases_keys` | over all registry composites, no node's prompt mentions a key from a phase it is not in |
| `test_no_child_node_in_the_recordings_produced_parent_keys` | regression on the 16-of-46 measurement, run against the recordings |

Plus the existing 184 must stay green, and the v1 trace lock byte-identical.

---

## 4. Acceptance criteria

| # | Criterion | Falsified by |
|---|---|---|
| F1 | No node's prompt carries a key from another phase | test over all composites |
| F2 | Composites satisfied by no model: 14 → **≤7** | re-recording all 14 |
| F3 | Child nodes producing parent keys: 16 of 46 → 0 | recording scan |
| F4 | Primitives do not regress (42 clean is a floor) | full 83 re-record |
| F5 | No assert weakened — 0 expressions changed | HEAD-vs-tree parse |
| F6 | 184+ tests green, `make check` clean | CI |

**F2 is the point.** F1 and F3 are mechanism: they prove the prompt changed. F2 is
whether it mattered. Halving is the bar because two of the fourteen also fail their
*own* contract, which this fix does not touch.

## 5. Risks

| Risk | Mitigation |
|---|---|
| Bug 2 is independent and composites stay broken | F2 measures it; if it fails the audit leads with that and the reconcile fallback is v1.7 |
| Scoping breaks primitives | F4 makes 42-clean a floor, and the trace lock covers mechanics |
| Another wrong hypothesis | §2 commits to measuring before deciding, which is the specific correction from three prior misses |
