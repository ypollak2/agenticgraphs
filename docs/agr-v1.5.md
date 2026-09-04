> **Superseded by [AGR v1.8](agr-v1.8.md).** This page describes an earlier version and is kept for the record; the current spec is agr-v1.8.md.

# AGR v1.5 — every node declares

One enum value, one lint, one migration. Third version running where the fix was to
*use* fields that already existed rather than add new ones.

## Correcting v1.4's diagnosis

v1.4 shipped saying `ab-test-analysis` failed because *"the contract has a joint
precondition no single node owns"*. The recordings say otherwise — both keys are
declared on **one** node:

```yaml
- id: judge
  outputs: [claimed_effect, output, recomputed_effect]
assert: "abs(output.recomputed_effect - output.claimed_effect) < 0.01"
```

One producer. Nothing joint. What the recordings actually showed was the two nodes
*upstream* of the judge:

```jsonc
{"keys": ["recomputed_effect", "claimed_effect"]}   // position-a, qwen3-coder:30b
{"keys_responsible": ["recomputed_effect"]}         // position-a, qwen2.5-coder:7b
```

They declared no outputs, so the prompt fell back to *"Return the keys this step is
responsible for"* — a question about the node's **job**, which the models answered
literally, naming keys instead of producing values. The judge downstream received
an empty blackboard and correctly emitted `null`.

## The gap

```
nodes (expanded):                      346
  declaring NO outputs:                103   (29%)
  of those, feeding a downstream node: 103   (all of them)
graphs with ≥1 silent node:             66 of 83
```

v1.4's lint asked whether *verification* had producers. Nothing asked whether a
node's **successors** have anything to consume.

## The lint

```
lint: nodes ['position-a', 'position-b'] have outgoing edges but declare no
      outputs — their successors have nothing to consume
```

Error at `apiVersion: agr/v1.5`, advisory below. Terminal nodes are exempt: a node
nothing depends on owes nothing. A `kind: subgraph` phase is exempt too — it
delegates, and the child declares.

## Inputs become reachability-checked

v1.1 added `inputs` and checked set membership — *does this key exist anywhere in
the graph*. That passes even when the only producer runs strictly downstream and
the value can never arrive. v1.5 checks whether a producer can actually **reach**
the consumer, computed as a fixed point because AGR graphs are deliberately cyclic.

This was only checkable once every dependent node had an output to be reachable
*from*.

## Joint preconditions get an advisory, not machinery

6 of 135 asserts genuinely span two producing nodes:

```
warn: assert spans keys from ['profile', 'explore'] — both must survive to the
      end for the check to be meaningful
```

Advisory only. It is a documentation problem, and inventing a `requires_all` field
for six cases would be exactly the optional-and-unused surface this version exists
to stop creating.

## Why this kept happening

| Version | The gap | Scope |
|---|---|---|
| v1.2 | `LLMRunner` never stated the contract | all nodes |
| v1.3 | JSON extraction too brittle to read the answer | all nodes |
| v1.4 | verification keys nothing declared | 123 keys |
| v1.5 | nodes with no declared output at all | 103 nodes |

Each time the artifact looked complete and the runtime had nothing to work with.
The pattern is worth naming: **anything optional in the spec ends up unused, and
anything unused ends up load-bearing by accident.** v1.1 made `outputs` optional;
29% of nodes took that option and the registry depended on them anyway.

v1.5 adds no optional field.

## What it bought

`ab-test-analysis` — the graph that failed every model for three versions — passes
on `qwen3-coder:30b`. It still fails on the two smaller models, which is a real
result about model capability rather than about the contract.
