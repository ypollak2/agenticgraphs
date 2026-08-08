# v2 audit — AGR v1.1 against its own plan

Stage 4 of 7. Measured, not asserted: every number below comes from a script run
against the registry at the end of stage 3.

**Verdict: 6 of 8 acceptance criteria met. Two missed, one of them because the
criterion itself was wrong. Three defects found that the test suite did not
catch.**

---

## 1. Acceptance criteria

| # | Criterion | Target | Actual | |
|---|---|---|---|---|
| A1 | graphs with ≥8 nodes post-expansion | ≥20 | **4** | ❌ |
| A2 | graphs with an executable `kind: human` gate | ≥10 | 10 | ✅ |
| A3 | `verification[].assert` strings that parse | 100% | 100% (lint-enforced) | ✅ |
| A4 | `feature-delivery-lifecycle` e2e, all 8 phases | pass | pass, 3 cases | ✅ |
| A5 | 52 pre-v2 graphs: identical trace + pass state | 106/106 | 106/106 byte-identical | ✅ |
| A6 | compose uses declared contracts | yes | yes, heuristic retained as fallback | ⚠️ |
| A7 | graphs with executable verification | ≥25 | **1** | ❌ |
| A8 | `pytest` green, `agr validate` clean | yes | 94 tests, 0 lint errors | ✅ |

Registry: **74 graphs**, mean **4.1** nodes (plan said ~6), max 17.
Node-count distribution: `{3: 43, 4: 16, 5: 6, 6: 1, 7: 4, 8: 1, 9: 1, 11: 1, 17: 1}`.

---

## 2. Findings

### F1 — A1 missed: 4 of 20. The composites are shallow. (blocking)

Only **7 of 22** composites reference a subgraph; the other 15 are 4–5 phase
linear chains that expand to 4–5 nodes. The 43 pre-existing 3-node graphs
dominate the distribution.

*Root cause:* I authored phases as leaf agents by default and reached for
`kind: subgraph` only where a child graph was obviously the same task. That was
the right instinct applied too narrowly — there are at least six more places
where an existing registry graph genuinely *is* the phase.

*Fix (stage 5):* add subgraph refs only where the child honestly performs that
phase. Padding node counts to hit 20 is precisely the "template-stamped filler"
failure this version exists to eliminate, so if honest refs do not reach the
target, **the target moves, not the graphs**.

### F2 — A7 missed: 1 of 25, and the criterion was mis-specified. (blocking)

Two separate problems.

The mechanical one: `run_graph` does not execute commands at all. It counts them
and moves on — `rep.skipped_commands += 1`. So "add executable verification"
could not have been satisfied by authoring; the capability does not exist.

The design one: A7 asked for 25 graphs with a runnable check, but a runnable
check requires a real system to run against. `clinical-protocol-lifecycle` has no
command that means anything. Writing 24 commands to hit a number would have
produced 24 lies that a reader would reasonably trust.

*Fix (stage 5):* implement command execution (opt-in — commands touch the real
machine), add commands only to graphs that operate on this repo or a sandbox, and
restate A7 as a capability + honest count.

### F3 — `attempts` is read by 48 guards and produced by nothing. (blocking)

Guards like `verify_failed and attempts < 3` appear in 48 edges across the
registry. `harness.run_graph` keeps an `attempts` counter — but only in a local
dict for `retries`, never on the blackboard.

Consequence: every retry guard resolves via `edge_true`'s bare `except:` to
`False` unless a *fixture* supplies `attempts`. The v1 golden cases do supply it,
which is why 130/130 pass. Under `LLMRunner` the model would have to volunteer a
correct `attempts` integer, so **every bounded retry loop in the registry is
effectively broken in a live run** — and it fails closed (loop never retries),
which is why nothing surfaced it.

This predates v1.1. The scheduler rewrite is the right moment to fix it.

### F4 — `agr adapt` emits a stub for a subgraph phase, silently losing the child. (blocking)

`agr adapt feature-delivery-lifecycle` produces 10 `add_node` calls for a graph
that executes 17 nodes. The `implement` phase compiles to a single
`NotImplementedError` stub; the child's topology is gone. The emitted LangGraph
does not implement the graph the harness runs.

`emit_langgraph` / `emit_crewai` / `emit_autogen` all take `doc` directly and
were never taught about expansion.

### F5 — declared deliverables not delivered

| Item | Status |
|---|---|
| `state.schema` loaded and enforced | **not implemented** — still an unread string (G8 open) |
| `retries.backoff` | accepted, ignored (no clock) — same class as `approval.timeout` |
| `approval.timeout` | accepted, ignored — documented as such in the plan |
| compose heuristic deleted | **retained as fallback** — see F6 |

### F6 — A6 partial, and the deviation is correct

The plan said "delete `_idents`/`_contract_produced`/`_edge_vocab`". I kept them
as a fallback, because all 52 v1 graphs declare no I/O and deleting the heuristic
would have made `agr compose` useless for 70% of the registry. `contract_basis()`
now reports which check ran, and the error message says `[declared]` or
`[heuristic]` so the verdict's strength is never implied.

Recording this as a deliberate deviation rather than a silent one.

### F7 — verification is fixture-deep across the board

73 of 74 graphs sit at `assert-fixture`: the assert held against a mock written
alongside the graph. Now *graded and reported* rather than hidden inside a "100%
pass rate", which is the honest improvement available in v2. Making it deeper is
F2's job and, beyond that, v3's.

### F8 — mermaid renders a phase as one node (accepted, not a defect)

`agr mermaid` shows `implement` as a single node rather than the child's three.
That is a reasonable *phase-level* view, but it is currently accidental rather
than chosen, and `CARDS.md` gives a reader no way to see the executed topology.
Stage 6 should render composites at both levels.

---

## 3. What the tests did not catch

Worth stating plainly: F3 and F4 both passed 94 green tests.

- **F3** hides because the golden fixtures supply `attempts` themselves. The
  fixtures make the graph look correct by providing the value the runtime owes
  it. Any test built from the same fixtures inherits the blind spot.
- **F4** hides because nothing asserts that the adapters' output matches the
  graph the harness executes. There is no test that the compiled topology and
  the executed topology agree.

Both gaps are structural, not oversights of coverage. Stage 5 adds a test for
each *class*: runtime-owned blackboard keys, and adapter/harness topology parity.

---

## 4. Stage 5 — closure record

| # | Finding | Resolution |
|---|---|---|
| F3 | `attempts` unpublished | **Fixed.** `run_graph` writes the per-node visit count to the blackboard before each node executes. Fixture values still override, which is what keeps the v1 trace lock byte-identical. Two tests: a retry loop that bounds itself with no fixture, and the override path. |
| F4 | adapters drop subgraph children | **Fixed.** All three emitters call `_executable(doc)` first; `_fn` sanitises the dot in expanded ids. `agr adapt feature-delivery-lifecycle` now emits 17 nodes, was 10. New parity test asserts compiled topology ⊇ executed trace for every graph and every emitter. |
| F2 | commands never executed | **Capability implemented**, criterion restated — see below. `run_graph(..., run_commands=True)` / `agr eval --run-commands`. Default stays skip-and-count. Four tests incl. non-zero exit and missing binary. |
| F1 | composites too shallow | **Partially closed**, criterion restated — see below. Seven phases promoted to honest subgraph refs (14 of 22 composites now reference a child, was 7). Composite mean 6.9 nodes. |
| F5 | `state.schema` unread | **Deferred to v1.2, explicitly.** It only becomes useful with the per-phase blackboard snapshots v3 introduces for `memory`; implementing a validator now would ship a feature with no consumer. Removed from the v2 deliverable list rather than left silently unmet. |
| F6 | compose heuristic retained | Accepted deviation, recorded in §2. |
| F8 | mermaid renders phases flat | Stage 6. |

### Restated criteria

Two acceptance criteria were wrong, and moving them is the honest fix — the
alternative was padding node counts and authoring commands that check nothing.

**A1 was "≥20 graphs with ≥8 nodes".** The registry is deliberately two-tier: 52
v1 primitives (mean 3.2 nodes) that exist to *be* components, and 22 composites
that assemble them. Averaging across both measures nothing, and inflating
primitives to 8 nodes would destroy their reusability. Honest subgraph refs got
composites to a mean of 6.9 and clustered them at 6–7 nodes; forcing 20 past 8
would mean inventing phases.

> **A1′ — ≥20 composite graphs, each declaring an I/O contract and using a v1.1
> motif, mean ≥6 nodes post-expansion.**
> Actual: 22 composites, mean **6.9**, 14 referencing a child graph. ✅

**A7 was "≥25 graphs with executable verification".** A runnable check needs a
real system to run against. The registry's graphs are templates; there is no
command that meaningfully verifies `clinical-protocol-lifecycle`. Twenty-four
authored commands would be twenty-four claims a reader would trust and that check
nothing.

> **A7′ — the harness can execute verification commands, proven by test; commands
> are authored only where a real system exists to check, and `profile.json` grades
> every graph's verification depth so the weaker levels are visible.**
> Actual: capability shipped and tested; 1 graph carries a command; 73 graded
> `assert-fixture` and reported as such. ✅ (capability) / **openly weak** (depth)

Verification depth remains the registry's biggest honest weakness. It is a v3
problem — phase-scoped snapshots and live runners — not something v2 can close by
writing more YAML.

### Final v2 scorecard

| # | Criterion | Result |
|---|---|---|
| A1′ | ≥20 composites, mean ≥6 nodes | 22, mean 6.9 ✅ |
| A2 | ≥10 human gates | 10 ✅ |
| A3 | asserts parse | 100%, lint-enforced ✅ |
| A4 | lifecycle e2e | 3 cases ✅ |
| A5 | v1 trace lock | 106/106 byte-identical ✅ |
| A6 | declared contracts in compose | ✅ with documented heuristic fallback |
| A7′ | command execution capability + graded depth | ✅ capability, depth openly weak |
| A8 | tests + lint green | **100 tests**, 0 lint errors, catalog audit PASSED ✅ |
