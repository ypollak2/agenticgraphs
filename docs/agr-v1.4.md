> **Superseded by [AGR v1.8](agr-v1.8.md).** This page describes an earlier version and is kept for the record; the current spec is agr-v1.8.md.

# AGR v1.4 — connect the contracts

No new machinery. One enum value, one lint, and a migration — because the fields
needed to express this contract have existed since v1.1 and simply were not used.

## The gap

A graph had **two vocabularies with nothing checking they referred to the same
things**: node `inputs`/`outputs` on one side, `verification[].assert` on the
other. Measured at the start of v1.4:

```
verification keys across registry: 183
keys no node declares:            123      (67%)
graphs affected:                   73 of 83
```

That is how four contracts stayed structurally valid, passed the entire suite, and
were satisfiable by no model: nothing ever asked whether the nodes that run before
a verifier produce what it asserts on.

## The lint

```
lint: verification asserts on ['recomputed_effect'] which no node declares as an
      output and state.inputs does not supply
```

An **error** at `apiVersion: agr/v1.4`; below that it is advisory and returned by
`lint_advisories()`, never by `lint_graph()`.

That separation is load-bearing. An earlier draft returned warnings from
`lint_graph`, and since every caller treats that list as fatal, `agr infuse`
started refusing every graph in the registry with *"infusion rejected by gate:
warn: ..."*. A non-blocking warning that flows through a blocking channel is not a
warning.

## `asserted_keys` — AST, not regex

Keys are `output.<attr>` accesses plus free bare names, minus comprehension-bound
variables, level literals and builtins.

```python
asserted_keys("all(f.file and f.line for f in output.findings)") == {"findings"}
```

A regex version counted `f`, `v` and `for` as blackboard keys — a wrong number
that looked convincingly like a finding.

## Declaring nothing is not a defence

`unconnected_keys` briefly began with `if not produced: return set()`, on the
reasoning that *"a node that declares nothing makes no promise to break"*. That
exempted precisely the worst case: `code-review-pipeline` asserted on
`output.verdict` while declaring no outputs at all, so it read as fully connected
and was promoted to v1.4. Declaring nothing is the maximal form of the gap, not an
exemption from it.

## The migration came from the fixtures

Which node establishes which key is not guessable from the YAML — but every graph
has a golden case naming, per node, exactly what it emits.
`scripts/derive_outputs.py` reads those and declares each key where the evidence
says it belongs. 125 declarations across 83 graphs.

**No assert was modified.** The cheap way to make 123 unmet keys vanish is to
delete the asserts referencing them, so the migration is verified by parsing every
graph at HEAD and in the working tree and comparing the assert strings:
**0 changed.**

## `LLMRunner` tells the assembler where values come from

A node whose declared outputs include `output` is not computing those facts — it is
assembling them from what upstream nodes established. It now gets:

> The `output` object must contain: [...]. Take each value from the blackboard
> above — do not invent them.

v1.3 declared the asserted keys on the terminal and re-recorded: 0 of 12 runs
passed, because asking one node to *return* facts it never had is not the same as
asking it to *assemble* facts it can see.

## What this actually bought

Contracts satisfied by no recorded model: **4 → 1**.

| Graph | before | after |
|---|---|---|
| `earnings-call-digest` | ❌ | ✅ |
| `benchmark-driven-optimization-search` | ❌ | ✅ |
| `differential-diagnosis-ensemble` | ❌ | ✅ (7B only) |
| `ab-test-analysis` | ❌ | ❌ |

The acceptance criterion was *≥3 of 4 on `qwen3-coder:30b`* and only 2 pass there —
`differential-diagnosis-ensemble` is satisfied by the 7B model and not the 30B one.
**The criterion is missed as written**, and the 4→1 number does not erase that.

## Not in v1.4 — the joint precondition

`ab-test-analysis` asserts across **two facts produced by different nodes**:

```yaml
assert: "abs(output.recomputed_effect - output.claimed_effect) < 0.01"
```

Every model produced one and left the other `None`. Declaring both on the right
nodes tells each what it owes; nothing states that both must hold *at the same
time* before the assert is meaningful. That is a different problem from the one
v1.4 solved — v1.3 was "the contract is not stated", v1.4 is "the contract is
stated per node", and this is "the contract has a joint precondition no single node
owns" — and it is the v1.5 item.
