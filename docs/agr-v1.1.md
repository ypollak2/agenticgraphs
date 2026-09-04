> **Superseded by [AGR v1.8](agr-v1.8.md).** This page describes an earlier version and is kept for the record; the current spec is agr-v1.8.md.

# AGR v1.1 — composites

Additive over AGR v1. Every v1 graph validates unchanged, and the scheduler was
replaced against a [trace lock](../tests/fixtures/v1_trace_lock.json) proving all
106 pre-existing eval cases execute byte-identically.

Declare `apiVersion: agr/v1.1` to use anything below; a lint error fires if you
use a v1.1 feature under `agr/v1`.

---

## `kind: subgraph` — a phase that *is* another graph

```yaml
- id: audit
  speciality: supervisor
  kind: subgraph
  ref: software-engineering/code-review-pipeline   # <category>/<name>
  inputs: [patch]
  outputs: [verdict, findings]
```

Expanded at load time, not executed recursively. The child's nodes are inlined
with the phase id as prefix (`audit.triage`, `audit.synthesize`), the parent's
edges are rewired onto the child's entry and terminal nodes, and `max_steps` is
summed.

Inline expansion keeps `run_graph`, `agr adapt`, `agr mermaid` and
`structural_profile` working on a flat node list, and keeps traces readable.

**Boundary rules**
- The phase's `inputs` transfer to the child's entry nodes, `outputs` to its
  terminals — otherwise the declared contract would evaporate on expansion.
- `join` on the phase governs how the child is entered.
- **Child `verification` is not merged into the parent.** Every graph writes to a
  single `output` key, so a child's asserts only hold at the instant its terminal
  ran; merged upward they evaluate against a snapshot the parent has since
  overwritten. Phase-scoped verification needs blackboard snapshots — v1.2. Until
  then a lint requires composites to declare their own verification.
- Nesting depth is capped at 3; reference cycles raise `SubgraphError`.
- A subgraph node declares no `abilities` — they live in the child.

## `join` — when a multi-predecessor node is ready

```yaml
- id: synthesize
  join: all     # any (default) | all | quorum(2)
```

| `join` | Ready when |
|---|---|
| `any` | ≥1 incoming forward flow edge is taken — **v1 behaviour, the default** |
| `all` | every incoming forward flow edge is *settled*, and ≥1 taken |
| `quorum(n)` | ≥n incoming forward flow edges taken |

Back-edges (retries) and compensate edges never count toward a join — a retry
edge is unresolved by construction, so counting it would deadlock every `all`.

**Settlement** is the subtle part. When a router picks one branch, the other
branch's node never runs, so its outgoing edge never *resolves*. A naive `all`
waits forever. An edge is settled if it resolved, or if its source is provably
dead: not queued, never ran, and all of its own incoming edges settled without
being taken. Settlement recurses upward with a cycle guard, and is evaluated with
the queue drained — asking "is X dead?" while X is queued is circular.

## `kind: human` — an approval gate

```yaml
- id: release-approval
  kind: human
  speciality: approver
  abilities: [approve]
  approval:
    contract: "signed_off == true and verdict == 'approve'"
    timeout: 24h            # recorded, NOT enforced — the harness has no clock
    on_timeout: escalate    # escalate | reject | proceed
```

After the node runs, `contract` is evaluated against the blackboard. If it is
false, **every outgoing flow edge is blocked** — only error and compensate edges
can fire.

`LLMRunner.approve` raises `HumanGateRequired` rather than sign its own gate.
`agr eval --auto-approve` bypasses it for CI and stamps the report
`auto_approved`, so the resulting profile can never be mistaken for a real
sign-off.

## Edge kinds — `flow`, `error`, `compensate`

```yaml
edges:
  - {from: cutover, to: undo-cutover, kind: compensate, when: "cutover_failed"}
  - {from: release, to: rollback, kind: error}
```

| kind | Fires when |
|---|---|
| `flow` (default) | the node did not error, its gate was not rejected, and `when` holds |
| `error` | the node's output carries `error`, and `when` holds |
| `compensate` | `when` holds; exempt from back-edge lint and from join accounting |

`on_error: <node>` on a node is sugar for an error edge. A node reached only by
an error or compensate edge is *forced* ready — no join rule can vouch for a node
that is off the forward-flow graph entirely.

**Saga lint:** in a graph whose name ends `-saga`, any node holding an
`risk: execute` ability must have an outgoing compensate edge. Compensators
themselves are exempt.

## `retries`

```yaml
- id: cutover
  retries: {max: 2, backoff: linear}   # backoff recorded, NOT enforced (no clock)
```

On `error` in a node's output, the node is re-queued ahead of the frontier up to
`max` times before error edges fire.

## Declared I/O contracts

```yaml
state:
  inputs: [goal, repo]        # supplied at graph entry
nodes:
  - id: plan
    inputs:  [research_brief]
    outputs: [plan, acceptance_criteria]
```

Optional and opt-in — a node that declares nothing is not checked. A declared
input must be produced by some node's `outputs` or supplied by `state.inputs`.

`agr compose` prefers this contract when both graphs declare one, and falls back
to the v1 identifier heuristic otherwise. `contract_basis()` and the error
message report which check ran, so a `[heuristic]` verdict is never mistaken for
a proof. `agr compose --mode subgraph` emits a parent that *references* both
graphs instead of splicing them.

## Verification

```yaml
verification:
  - describe: "the audit cleared before anything shipped"   # prose (v1.1)
    assert:   "output.verdict == 'approve'"                 # must ast.parse
  - command: "pytest -q"                                     # opt-in execution
```

`assert` that does not parse is a **lint error**. `describe` alone is legal but
grades as unverified.

Commands are **skipped by default** — counted, never silently treated as passing.
`agr eval --run-commands` executes them (real code on the real machine); a
non-zero exit fails the run.

`profile.json` carries `verification_depth`, weakest first:

| depth | meaning |
|---|---|
| `describe-only` | prose; nothing machine-checked |
| `assert-fixture` | assert held against a mock fixture — where 73 of 74 graphs sit |
| `assert-live` | assert held against real model output |
| `command` | an executable check ran and exited 0 |

## Entry nodes

One shared definition across harness, linter and compose:
**a node with no incoming *forward* edge of any kind.**

Direction decides. A backward edge (retry, compensation) never disqualifies a
node — it cannot be how a graph begins. Any forward edge does, whatever its kind
or condition.

Two failures shaped this rule, both worth knowing:

- *"No incoming edge at all"* made any graph whose retry edge pointed back at its
  first node entry-less. It executed **zero steps** while linting clean.
- *"No incoming unconditional flow edge"* let a node reachable only by an error
  or compensate edge look like a start node. A rollback handler fired as step two
  of a release lifecycle, before the thing it compensates had run.

## Runtime-owned blackboard keys

`attempts` — the current node's visit count, written **before** each node runs.

48 edge guards across the registry read it (`verify_failed and attempts < 3`) and
nothing produced it: `edge_true` swallowed the `NameError` and returned False, so
every bounded retry loop silently failed closed. It was masked because golden
fixtures supplied the value the runtime owed. A fixture value still overrides the
runtime one, which is what keeps the v1 trace lock byte-identical.

## Not in v1.1

Declared and deliberately deferred, rather than silently unmet:

| | |
|---|---|
| `state.schema` | still an unread string — it has no consumer until phase snapshots exist (v1.2) |
| `approval.timeout`, `retries.backoff` | accepted and recorded, not enforced — the harness has no clock (v1.3) |
| phase-scoped verification | needs blackboard snapshots (v1.2) |
| `fan_out` cardinality | a `parallel_group` is still a label, not a fan-out (v1.2) |
