# v2 — "Long graphs" (AGR v1.1)

Stage 1 of 7. Implementation plan for the v2 slice of
[`graph-expansion-v2-v4.md`](graph-expansion-v2-v4.md).

**Goal:** make composite, multi-phase, gated workflows expressible *and runnable*.
The proof artifact is `feature-delivery-lifecycle` — research → plan → implement →
test → audit → fix → docs → release — running end-to-end under `agr eval`.

**Non-goals for v2:** search/MCTS, real fan-out cardinality, memory, triggers,
durability. Those are v3/v4 and are deliberately out.

---

## 1. Design decisions

Seven decisions, each with the alternative rejected and why.

### D1 — Versioning: additive schema, dual `apiVersion`

`apiVersion` becomes `enum: ["agr/v1", "agr/v1.1"]`. All new properties are
**optional**, so every existing graph still validates untouched. A new lint rule
`lint: uses v1.1 feature '<x>' but declares apiVersion agr/v1` catches drift.

*Rejected:* a separate `agr-graph-v1_1.schema.json`. Two schemas means two lint
paths and a permanent migration cliff for a registry that is 100% ours to migrate.

### D2 — Subgraphs expand inline at load time, not recursively at run time

```yaml
- id: implement
  kind: subgraph
  ref: software-engineering/bug-triage-and-fix
  speciality: executor          # still required by schema; describes the phase
```

`registry.expand_subgraphs(doc)` inlines the referenced graph's nodes with an
`implement.` id prefix, rewires the parent's in/out edges to the child's
entry/terminal nodes, and merges `verification` blocks. Depth cap 3, cycle
detection by ref-path.

Why inline: the existing interpreter, `agr adapt` codegen, `agr mermaid`, and
`structural_profile` all keep working with **zero changes**. Traces stay flat and
readable (`plan → implement.repro → implement.patch → implement.verify → test`).
Recursion would need every one of those to learn about nesting.

*Cost, stated honestly:* `max_steps` and budgets are parent-level only; a subgraph
cannot enforce its own step cap. Acceptable in v2, revisited in v4 with budgets.

### D3 — `join` defaults to `any` (no behavior change), `all` is opt-in

```yaml
- id: synthesize
  join: all        # any (default) | all | quorum(2)
```

Today a multi-predecessor node joins *by accident* — `harness.run_graph` appends
to a list frontier and skips ids already queued (`harness.py:167`). That is
order-dependent: if `synthesize` pops before `style-review` fires, it runs twice.

The fix is a real readiness check. For each node we track **edge resolution**: an
incoming edge is *resolved* once its source node has run and its `when` has been
evaluated (taken or not-taken).

| `join` | Node is ready when |
|---|---|
| `any` (default) | ≥1 incoming edge is resolved-taken |
| `all` | every incoming flow edge is resolved, and ≥1 is taken |
| `quorum(n)` | ≥n incoming edges are resolved-taken |

Back-edges (loops) are excluded from `all` accounting — otherwise a retry edge
would deadlock the join forever.

*Rejected:* defaulting to `all`. It is the semantically better default but it
silently changes 9 shipped graphs. Opt-in now; consider flipping the default in v3
once every graph declares intent.

### D4 — Node I/O contracts are declared, not inferred

```yaml
- id: plan
  inputs:  [research_brief]
  outputs: [plan, acceptance_criteria]
```

New lint rule: every key in a node's `inputs` must appear in some upstream node's
`outputs`, or in graph-level `state.inputs`. This closes **G3** and lets
`compose.py` delete its regex heuristic (`_idents`, `_contract_produced`,
`_edge_vocab`) in favour of a real set comparison.

Both fields stay optional in v1.1 — the 52 existing graphs declare nothing and
keep validating. Lint only fires when a node declares `inputs`.

### D5 — `kind: human` becomes executable

```yaml
- id: release-approval
  kind: human
  speciality: approver
  approval:
    contract: "signed_off == true"
    on_timeout: escalate        # escalate | reject | proceed
```

Runner protocol gains an optional `approve(node, bb) -> dict`. Three
implementations:

- `MockRunner` — reads the approval from the case fixture, same as any node.
- `LLMRunner` — **refuses**. A model must not sign its own approval gate. Raises
  `HumanGateRequired` unless `--auto-approve` is passed (CI only; the run report
  is stamped `auto_approved: true` and `profile.json` marks it non-authoritative).
- Interactive — out of scope for v2 (v4, with durability).

`timeout` is accepted and recorded but **not enforced** in v2 — there is no clock
in the harness. Documented as such rather than faked.

### D6 — Error and compensation are edge kinds

```yaml
edges:
  - {from: cutover, to: rollback, kind: compensate, when: "cutover_failed"}
  - {from: deploy,  to: page-oncall, kind: error}
```

`kind: flow` (default) | `error` | `compensate`. The interpreter treats `error`
edges as taken only when the source node's output carries `error`, and
`compensate` edges as taken only when their `when` holds — but a compensate edge
is **exempt from the unconditional-back-edge lint** and from `all`-join
accounting, because it is a reverse path by construction.

New lint: a `saga`-motif graph must have a compensate edge for every node that
declares an ability with `risk: execute`.

### D7 — lock in parseable asserts; grade verification by *depth*

**Corrected 2026-08-08.** The original plan claimed 51 of 52 graphs carried prose
in `verification[].assert`. That was wrong — all 53 asserts `ast.parse` cleanly.
The prose lives in `termination.contract`, which is never parsed by anything.

The real gap is narrower and different: 52 of 53 asserts are only ever evaluated
against `MockRunner` fixtures written alongside the graph. An assert like
`output.verdict in ['approve','request_changes']` passes because the fixture
*says* `verdict: approve`. It proves the graph plumbs the key through. It does not
prove a verdict was earned. Only 1 graph (`verifier-swarm`) carries an executable
`command`, and `run_graph` **skips** commands entirely (`rep.skipped_commands += 1`).

So v1.1 does three things instead of a migration:

1. **Lint `assert` must parse** — a cheap guard so the property we already have by
   luck becomes one we have by contract.
2. **Add `describe`** as the prose home, so `termination.contract` text can move
   down to the specific check it describes. Optional, non-breaking.
3. **Grade verification depth** in `profile.json` and the scoreboard:

   | depth | meaning |
   |---|---|
   | `command` | an executable check ran and exited 0 |
   | `assert-live` | assert held against `LLMRunner` output |
   | `assert-fixture` | assert held against a mock fixture — **today's 52** |
   | `describe-only` | prose, unverified |

   This makes the honest number visible rather than reporting "52/52 at 100%".

Migration cost drops from ~5h to ~1h (schema + scoreboard column).

---

## 2. Schema diff

`spec/agr-graph.schema.json`:

```jsonc
{
  "apiVersion": { "enum": ["agr/v1", "agr/v1.1"] },        // was const

  "nodes[]": {
    "kind": { "enum": ["agent","verifier","human","router","subgraph"] },  // +subgraph
    "ref":      { "type": "string", "pattern": "^[a-z0-9-]+/[a-z0-9-]+$" }, // subgraph only
    "join":     { "type": "string", "pattern": "^(any|all|quorum\\([0-9]+\\))$" },
    "inputs":   { "type": "array", "items": {"type":"string"} },
    "outputs":  { "type": "array", "items": {"type":"string"} },
    "retries":  { "max": "integer 0..5", "backoff": "enum[none,linear,exponential]" },
    "on_error": { "type": "string" },                       // sugar for an error edge
    "approval": { "contract": "string", "on_timeout": "enum[escalate,reject,proceed]",
                  "timeout": "string" }                     // human only; timeout unenforced
  },

  "edges[]": {
    "kind": { "enum": ["flow","error","compensate"], "default": "flow" }
  },

  "state": {
    "schema": "string (path to a JSON Schema, now actually loaded)",
    "inputs": { "type": "array", "items": {"type":"string"} }   // graph-level entry keys
  },

  "verification[]": {
    "describe": { "type": "string" },                      // NEW: prose home
    "assert":   { "type": "string" },                      // now: must ast.parse
    "command":  { "type": "string" }
    // anyOf: describe | assert | command
  }
}
```

Conditional constraints (JSON Schema `allOf`/`if-then`):
- `kind: subgraph` ⇒ `ref` required, `abilities` forbidden.
- `kind: human` ⇒ `approval` required.
- `ref` present ⇒ `kind: subgraph`.

---

## 3. Work breakdown

Ordered by dependency. Estimates assume the existing test suite stays green throughout.

| # | File | Change | Est. |
|---|---|---|---|
| 1 | `spec/agr-graph.schema.json` | the diff in §2 | 2h |
| 2 | `src/agenticgraphs/registry.py` | `expand_subgraphs(doc, root, depth=0)` — inline, namespace, cycle-detect | 4h |
| 3 | `src/agenticgraphs/harness.py` | scheduler rewrite: edge-resolution tracking, `join` semantics, `error`/`compensate` edge kinds, `retries`, human-gate protocol, `HumanGateRequired` | 8h |
| 4 | `src/agenticgraphs/validate.py` | new lints: v1.1-feature-vs-apiVersion, `assert` must parse, I/O contract, subgraph ref resolves, human needs approval, saga needs compensation, compensate-edge exemptions | 5h |
| 5 | `src/agenticgraphs/compose.py` | delete `_idents`/`_contract_produced`/`_edge_vocab`; use declared `inputs`/`outputs`; emit `kind: subgraph` refs instead of text-splicing | 4h |
| 6 | `scripts/gen_graphs.py` | motif library (composable) + 5 new motifs: `lifecycle`, `human-gate`, `supervisor-hierarchy`, `saga`, `escalation-ladder` | 5h |
| 7 | `specialities/*.yaml`, `abilities/*.yaml` | ~12 new specialities (`approver`, `release-manager`, `docs-writer`, `qa-lead`, `sre`, `counsel`, `controller`, `recruiter`, `buyer`, `migrator`, `supervisor`, `compensator`) + ~10 abilities (`approve`, `rollback`, `cut_release`, `write_docs`, `run_suite`, `shadow_write`, `backfill`, `negotiate`, `screen`, `file_record`) | 3h |
| 8 | `graphs/**` | 22 new composite graphs (§4) | 12h |
| 9 | `graphs/**` (existing 52) | assert migration per D7 | 5h |
| 10 | `evals/**` | golden cases for 22 new graphs, incl. phase-level fixtures | 6h |
| 11 | `tests/` | §5 | 6h |

**Total ≈ 60h of work → 2–3 calendar weeks.** Steps 1–5 are the critical path;
8–10 parallelize.

---

## 4. The 22 graphs

Every one is a **composite** (8–16 nodes after subgraph expansion) and graduates
from an existing `usecases/catalog.yaml` entry, preserving the audit invariant.

### Tier A — flagship lifecycles (5)

| Graph | Domain | Phases | New motif |
|---|---|---|---|
| `feature-delivery-lifecycle` | software-engineering | research → plan → implement → test → audit → fix → **docs** → release-gate → release | lifecycle |
| `incident-lifecycle` | devops-sre | detect → triage → mitigate → verify → postmortem → action-items | lifecycle |
| `vuln-remediation-lifecycle` | security | ingest → prioritize → repro → patch → verify → **disclose gate** | lifecycle + human-gate |
| `schema-migration-saga` | data-analytics | plan → shadow-write → backfill → cutover, each with a compensator | saga |
| `framework-migration` | software-engineering | inventory → slice → per-slice PEV **subgraph** → integration gate | supervisor-hierarchy |

`feature-delivery-lifecycle` is the acceptance artifact. Its `implement` phase is
`kind: subgraph → software-engineering/bug-triage-and-fix`, its `test` phase is
`kind: subgraph → software-engineering/test-suite-generation`, and its `audit`
phase is `kind: subgraph → software-engineering/code-review-pipeline` — which
demonstrates that the existing flat library becomes the *component library* for
composites. That is the whole thesis of v2.

### Tier B — human-gated, regulated domains (6)

`clinical-protocol-lifecycle` (healthcare-science) · `contract-lifecycle`
(legal-compliance) · `regulatory-filing-lifecycle` (finance) ·
`gdpr-data-audit` (legal-compliance) · `trial-eligibility-screener`
(healthcare-science) · `compliance-evidence-collector` (security)

### Tier C — orphan-domain fills (11)

Closes the worst coverage holes — `creative-production` (1 graph today),
`hr-people` (1), `logistics-retail` (1):

`hiring-lifecycle`, `onboarding-plan-builder`, `performance-cycle-summarizer`
(hr-people) · `procurement-lifecycle`, `vendor-comparison-matrix`,
`invoice-reconciliation` (business-ops) · `book-editing-pipeline`,
`podcast-production-pipeline`, `screenplay-coverage` (creative-production) ·
`supplier-risk-monitor`, `product-listing-pipeline` (logistics-retail)

**Post-v2:** 74 graphs, 13 motifs, catalog coverage 74/114, three domains off the
floor of 1.

---

## 5. Test plan (previews stage 3)

| Layer | Coverage |
|---|---|
| Schema | every new field accepted; conditional constraints reject bad combos; a v1 doc still validates |
| Lint | one focused test per new rule, each asserting the exact message |
| Harness — join | `all` waits for both predecessors; `all` does not deadlock on a back-edge; `any` preserves today's trace on all 52 existing graphs (**regression lock**) |
| Harness — subgraph | expansion namespaces ids; rewires entry/terminal; depth cap raises; self-reference raises |
| Harness — human | `MockRunner` reads fixture; `LLMRunner` raises `HumanGateRequired`; `--auto-approve` stamps the profile |
| Harness — error/compensate | error edge fires only on `error` in output; compensate runs after failure; compensate is lint-exempt |
| Compose | declared-contract match/mismatch; composed doc emits `kind: subgraph` |
| **e2e** | `feature-delivery-lifecycle` runs to completion, trace contains all 8 phases in order, subgraph-expanded ids present, contract asserts hold |
| Registry invariant | every catalog entry with a graph still validates; graph count matches README |

Regression lock is the important one: **all 52 existing graphs must produce a
byte-identical trace before and after the scheduler rewrite.** That test is
written first, from the current `profile.json` files.

---

## 6. Acceptance criteria

| # | Criterion | Measured by |
|---|---|---|
| A1 | ≥20 graphs with ≥8 nodes post-expansion | `agr profile` sweep |
| A2 | ≥10 graphs with an executable `kind: human` gate | grep + lint |
| A3 | 100% of `verification[].assert` strings `ast.parse` | lint, CI-enforced |
| A4 | `feature-delivery-lifecycle` passes `agr eval` e2e with all 8 phases in trace | test `test_e2e_lifecycle` |
| A5 | All 52 pre-v2 graphs: identical trace + pass state | regression lock test |
| A6 | `compose` uses declared contracts; heuristic code deleted | absence of `_idents` |
| A7 | Graphs with executable verification ≥ 25 (from 1) | scoreboard |
| A8 | `uv run pytest` green; `agr validate` clean across the registry | CI |

## 7. Risks

| Risk | Mitigation |
|---|---|
| Scheduler rewrite silently changes existing traces | A5 regression lock, written **before** the rewrite |
| Subgraph inlining explodes node counts and breaks mermaid/CARDS rendering | cap depth at 3; render subgraph phases as mermaid `subgraph` blocks; check CARDS.md regen in stage 6 |
| Assert migration becomes 52 hand-authored judgment calls | script the prose→`describe` move; hand-author asserts only where a real predicate exists; mark the rest `unverified` rather than faking it |
| 22 new graphs regress to template-stamped filler — the exact flaw v2 exists to fix | every Tier A graph is hand-authored; stage-4 audit explicitly checks motif diversity, not just count |

---

**Next stage:** v2.2 — implement. Critical path is items 1–5 in §3 (schema →
registry → harness → validate → compose), with the A5 regression lock written first.
