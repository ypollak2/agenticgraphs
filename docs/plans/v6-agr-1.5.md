# v6 — "Every node declares" (AGR v1.5)

Stage 1 of 7.

## 0. The v1.4 audit's diagnosis was wrong — correcting it first

v1.4 shipped saying `ab-test-analysis` fails because *"the contract has a joint
precondition no single node owns"*, and named that the v1.5 scope.

**That is not what the recordings show.** Both keys are declared on **one** node:

```yaml
- id: judge
  outputs: [claimed_effect, output, recomputed_effect]
assert: "abs(output.recomputed_effect - output.claimed_effect) < 0.01"
```

One producer, not two. Nothing joint about it.

What the recordings actually show is the two nodes **upstream** of the judge:

```jsonc
// position-a, qwen3-coder:30b          // position-a, qwen2.5-coder:7b
{"keys": ["recomputed_effect",          {"keys_responsible":
          "claimed_effect"]}                ["recomputed_effect"]}
```

They declare no outputs, so `LLMRunner` tells them *"Return the keys this step is
responsible for"* — and they answer that question literally, naming keys instead of
producing values. The judge then receives an empty blackboard and correctly emits
`null`. The contract was never the problem; **the two nodes feeding it have no
contract at all.**

Measured across the registry:

```
nodes (expanded):                    346
  declaring NO outputs:              103   (29%)
  of those, feeding a downstream node: 103   (all of them)
graphs with ≥1 such node:             66 of 83
```

v1.4's lint asked whether *verification* had producers. It never asked whether a
node's **successors** have anything to consume. 103 nodes are contractually silent
and every one of them starves something.

**Goal:** no node in the registry is silent about what it produces, and
`ab-test-analysis` passes on a real model.

*The joint-precondition case is real but small — 6 of 135 asserts span two
producing nodes. It is §2.4, not the headline.*

---

## 1. Why this keeps happening

Four versions, four instances of the same shape:

| Version | The gap | Nodes affected |
|---|---|---|
| v1.2 | `LLMRunner` never stated the contract | all |
| v1.3 | JSON extraction too brittle to read the answer | all |
| v1.4 | verification keys nothing declared | 123 keys |
| **v1.5** | **nodes with no declared output at all** | **103 nodes** |

Each time the artifact looked complete and the runtime had nothing to work with.
The pattern: **anything optional in the spec ends up unused, and anything unused
ends up load-bearing by accident.** v1.1 made `outputs` optional; 29% of nodes took
that option and the whole registry quietly depends on them anyway.

*So v1.5's rule: `outputs` stops being optional for any node with a successor.*

---

## 2. Design decisions

### D1 — A node with a successor must declare an output

```
lint: node 'position-a' has outgoing edges but declares no outputs — its
      successors have nothing to consume
```

Error at `apiVersion: agr/v1.5`, advisory below (the v1.4 channel split already
exists and is tested). Terminal nodes are exempt: a node nothing depends on owes
nothing.

### D2 — Fix the prompt that invites a meta-answer

`"Return the keys this step is responsible for"` is a question about the node's
job, and models answer it as one. Even after D1 there will be graphs authored
without declarations, so the fallback must not invite garbage:

> Return a JSON object of concrete **values** this step produces. Do not return
> key names, plans, or descriptions of what you would do.

Consumer-in-the-same-version rule: shipped with a re-record proving it.

### D3 — Declarations derived from fixtures again, extended to every node

`derive_outputs.py` already maps fixture emissions to nodes; v1.4 only ran it for
keys that *verification* asserts on. Widen it to every key any node's fixture
emits. Same evidence, same mechanism, larger scope.

### D4 — `inputs` become checkable, not just declarable

v1.1 added `inputs` and only lints nodes that opt in. With D1 giving every node
outputs, an `inputs` declaration finally has something to check against — so a
node's declared inputs must be produced by a node that can reach it, not merely
exist somewhere in the graph. Reachability, not set membership.

### D5 — Joint preconditions get a lint, not machinery

For the 6 asserts spanning two producers, add:

```
lint: verification asserts across keys from ['profile', 'explore'] — both must be
      present for the check to be meaningful
```

Advisory only. It is a **documentation** problem (the graph should say both facts
must survive to the end) and inventing a `requires_all` field for six cases would
be exactly the optional-and-unused surface §1 warns about.

---

## 3. Schema diff

```jsonc
"apiVersion": { "enum": [..., "agr/v1.5"] }
```

Again nothing else. Three versions running, the fix has been to *use* fields that
already exist rather than add new ones.

---

## 4. Work breakdown

| # | Change | Est. |
|---|---|---|
| 1 | D1 lint + advisory channel | 2h |
| 2 | D3 widen `derive_outputs.py`; migrate 103 nodes | 5h |
| 3 | D2 prompt fix | 1h |
| 4 | D4 reachability-aware `inputs` lint | 3h |
| 5 | D5 joint-precondition advisory | 2h |
| 6 | Re-record `ab-test-analysis` + the 27-graph sweep × 3 models | 4h |
| 7 | Tests, docs, scoreboard column | 5h |

**≈22h.**

---

## 5. Acceptance criteria

| # | Criterion | Falsified by |
|---|---|---|
| E1 | Nodes with a successor and no declared output: 103 → 0 | the measurement script |
| E2 | All 83 graphs at `agr/v1.5`, lint clean | `agr validate` |
| E3 | **`ab-test-analysis` passes on ≥1 real model** | recordings |
| E4 | Registry-wide live pass rate beats v1.4's baseline (7 clean / 19 split / 1 unsat) | `docs/contract-findings.md` |
| E5 | No model returns a key-name list where a value belongs | grep the recordings for `keys_responsible`-shaped output |
| E6 | No assert weakened — 0 expressions changed | HEAD-vs-tree parse |
| E7 | 166+ tests green, `make check` clean | CI |

**E3 is the point.** It is the single graph that has failed every model for three
versions. If it still fails, v1.5 has improved the registry and not solved the
thing it was scoped around — and the audit leads with that, as v1.4's did.

**E5 is the honest check on D2.** The prompt fix either stops the meta-answers or
it does not, and the recordings show which.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Deriving 103 declarations from fixtures bakes in fixture assumptions | E3/E4 are measured against real models, which fixtures cannot influence |
| `ab-test-analysis` fails again for a fourth reason | acceptable and reportable; the audit leads with it and v1.6 gets the next layer, not a quieter claim |
| D1 makes 66 graphs red before the migration lands | advisory below `agr/v1.5`, exactly as v1.4's split worked |
| Another optional field quietly goes unused | that is what §1 is for; v1.5 adds no optional field |
