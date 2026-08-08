# Graph expansion plan — v2 → v4

Audit of the shipped library, the topology research behind the gap list, and three
versioned releases that add depth (complex graphs) rather than more of the same shape.

Status: proposal. Measured against the repo at `a5e7b51`.

---

## 1. Audit — what is actually in the library today

All numbers computed from `graphs/*/*/graph.yaml`, `usecases/catalog.yaml`, `spec/`.

| Metric | Value |
|---|---|
| Graphs | 52 |
| Mean nodes / edges per graph | **3.2 / 3.0** |
| Largest graph | **4 nodes** (`cost-routed-research`, `code-review-pipeline`) |
| Distinct structural templates behind 49 of 52 graphs | **8** |
| Handcrafted graphs | 3 |
| Graphs with an executable `verification[].command` | **1 of 52** |
| Nodes with `kind: human` | **0** (schema supports it; nothing uses it) |
| Specialities defined / carrying 55% of all node slots | 20 / **3** (`producer` 35, `analyst` 30, `critic` 25 of 165) |
| Abilities defined / used ≥5 times | 20 / **8** |
| Catalog entries with no graph | **62 of 114** |

### 1.1 The core finding

The library is **wide and flat**. 15 domains are covered, but every graph is a
2–4 node primitive stamped from `scripts/gen_graphs.py`. The eight "patterns" are
not workflow archetypes — they are *motifs*: the smallest unit of agentic
control flow (fan-out, retry, route, critique). Real work composes many motifs.

Concretely: the lifecycle you named —
`research → plan → implement → test → audit → fix → docs → release` — is **8 phases,
each of which is itself a motif**. It cannot be expressed today. The closest
available move is `agr compose`, which text-splices two graphs offline and
already documents its own limitation:

> "the free identifiers B's entry edges need must be a subset of what A is known to
> produce … there is no formal input/output contract on nodes"
> — `src/agenticgraphs/compose.py`

That is the blocker. Depth is not a content problem, it is a **spec problem**.

### 1.2 Spec / runtime gaps blocking complex graphs

| # | Gap | Consequence | Evidence |
|---|---|---|---|
| G1 | No join semantics | A node with 2 predecessors joins *by accident* (frontier dedupe in `harness.run_graph`), not by contract. Reorder the queue and it double-runs. | `harness.py:145-171` |
| G2 | `parallel_group` is a label, not fan-out | "map over 40 shards" executes as **one** node visit. Map-reduce graphs do not actually map. | `harness.py` has no cardinality |
| G3 | No node I/O contract | Composition can only guess at compatibility via regex over `when`/`assert` strings. | `compose.py` docstring |
| G4 | Verification is fixture-deep, not execution-deep | All 53 asserts *do* parse as Python (corrected 2026-08-08). But 52 of 53 are only ever evaluated against `MockRunner` fixtures — they prove the graph plumbs a key through, not that anything was checked. Only 1 graph carries an executable `command`. `termination.contract` stays prose and is never parsed. | `evalcmd.py`, `harness.run_graph` |
| G5 | No subgraph node kind | Reuse is copy-paste or offline splice; no runtime hierarchy. | schema `nodes[].kind` enum |
| G6 | No budget / model / cost binding per node | `cost-routed-research` routes by *speciality name*, not by an enforceable budget. | schema has no budget field |
| G7 | No error/compensation edges | A failed side-effecting node has no rollback path. Fatal for anything that writes. | schema `edges` has only `when` |
| G8 | `state.schema` is a free string, never read | No typed blackboard. | schema, `harness.py` |
| G9 | No triggers | Every graph is request/response. Nothing can watch. | no `triggers` in schema |

### 1.3 Coverage gaps (content)

- **62 orphaned catalog entries**, incl. every entry in `creative-production` (7 of 8),
  `hr-people` (6 of 7), `logistics-retail` (6 of 7).
- **No lifecycle/composite graph** in any domain.
- **No adversarial pattern** (red-team/blue-team) despite a `security` domain.
- **No search pattern** (tree/beam/MCTS) — README already flags "AFlow-style MCTS
  search remains open."
- **No human-gate graph**, despite `kind: human` in the spec — which rules out the
  regulated-domain use cases (`healthcare-science`, `legal-compliance`, `finance`)
  where a human sign-off is the whole point.

---

## 2. Research — the topology gap list

Surveyed against the multi-agent orchestration literature and current framework
practice (LangGraph supervisor/hierarchy, AutoGen group chat, CrewAI flows,
Reflexion, Tree-of-Thought, AFlow, blackboard/BDI systems, saga/compensation from
distributed transactions, MAST failure taxonomy which this repo already lints against).

Shipped motifs (8): `pipeline`, `map-reduce`, `router`, `parallel-swarm`,
`generator-critic`, `debate`, `planner-executor-verifier`, `loop`.

Missing archetypes, ranked by value/effort:

| Archetype | Shape | Why it is worth building | Needs |
|---|---|---|---|
| **lifecycle** | N phases, each a motif; gates between phases | The single most-requested shape. Your SDLC example. Unlocks every "end-to-end" use case. | G1, G3, G5 |
| **human-gate** | agent → approval barrier → agent, with reject path | Only way to ship regulated-domain graphs honestly. | G1, G7 |
| **supervisor-hierarchy** | supervisor delegates to sub-supervisors; runtime graph-of-graphs | Scales past the 4-node ceiling without a 40-node flat blob. | G5 |
| **saga** | forward steps each paired with a compensating step | Required for any graph with side effects (deploy, migrate, provision). | G7 |
| **escalation-ladder** | tier-1 → tier-2 → tier-3 → human, each with an exit test | Cheapest-capable-first, with an honest floor. Generalizes `cost-routed-research`. | G6 |
| **reflexion** | act → evaluate → write lesson to memory → re-act | Loop that *learns* between attempts instead of retrying blind. | G8 |
| **tree-search** | branch k candidates → score → expand best → prune | The quality lever for design/optimization tasks. AFlow. | G2, G8 |
| **tournament** | bracket of pairwise judged rounds | Better than one-shot `debate` when there are >2 options. | G2 |
| **ensemble-quorum** | n independent solvers → vote/median → dissent report | Turns model variance into a calibration signal. | G2 |
| **red-team-blue-team** | attacker and defender alternate, adversary scores | Only pattern that produces evidence of *absence* of a flaw. | G1, G8 |
| **blackboard** | opportunistic agents read/write shared state, controller picks | Best fit for open-ended investigation (incidents, forensics). | G8 |
| **watch-loop** | trigger → assess → act-or-sleep, continuous | Turns the library from request/response into always-on. | G9 |
| **market/auction** | bidders quote cost+confidence, allocator awards | Formalizes routing when capability is uncertain. | G6 |

---

## 3. The plan — three versions

Each version ships **spec capability + graphs that need it**. Shipping graphs
without the spec change produces longer chains, not deeper graphs.

### v2 — "Long graphs" (AGR v1.1)

**Theme:** make composite, multi-phase, gated workflows expressible and runnable.

**Spec changes**

```yaml
# nodes[]
- id: implement
  speciality: executor
  kind: subgraph              # NEW: G5
  ref: software-engineering/bug-triage-and-fix
  inputs:  [plan, repo]       # NEW: G3
  outputs: [patch, tests]     # NEW: G3
  join: all                   # NEW: G1 — all | any | quorum(n)
  on_error: rollback-impl     # NEW: G7
  retries: {max: 2, backoff: linear}

- id: release-approval
  kind: human                 # NOW MEANINGFUL: G1
  speciality: approver
  approval: {contract: "signed_off == true", timeout: 24h, on_timeout: escalate}
```

Plus: `edges[].kind: {flow, error, compensate}`; `verification[].assert` must parse
as Python (lint error otherwise — closes G4); typed `state.schema` pointing at a
JSON Schema file (G8).

**New motifs:** `lifecycle`, `human-gate`, `supervisor-hierarchy`, `saga`, `escalation-ladder`.

**Graphs (target ~22, all composite, 8–16 nodes)**

| Graph | Domain | Phases |
|---|---|---|
| `feature-delivery-lifecycle` | software-engineering | research → plan → implement → test → audit → fix → docs → release *(your ask)* |
| `incident-lifecycle` | devops-sre | detect → triage → mitigate → verify → postmortem → action-items |
| `vuln-remediation-lifecycle` | security | ingest → prioritize → repro → patch → verify → disclose |
| `schema-migration-saga` | data-analytics | plan → shadow-write → backfill → cutover → **compensate on failure** |
| `framework-migration` | software-engineering | inventory → slice → per-slice PEV subgraph → integration gate |
| `clinical-protocol-lifecycle` | healthcare-science | draft → critic → **human sign-off** → registry filing |
| `contract-lifecycle` | legal-compliance | intake → redline → risk gate → **counsel approval** → execute |
| `regulatory-filing-lifecycle` | finance | collect → reconcile → **controller approval** → file → evidence |
| `hiring-lifecycle` | hr-people | JD → sourcing → screen swarm → interview loop → **panel decision** |
| `procurement-lifecycle` | business-ops | RFP → vendor matrix → negotiation → **approval gate** → onboard |
| …+12 filling `creative-production`, `logistics-retail`, `education` orphans | | |

**Also in v2:** upgrade `agr compose` to emit `kind: subgraph` references instead of
text-splicing; add `agr lint --strict` enforcing parseable asserts; retire prose asserts
across all 52 existing graphs.

**Acceptance:** ≥20 graphs with ≥8 nodes; ≥10 graphs with a real `human` gate;
100% of `verification[].assert` strings parse; `feature-delivery-lifecycle` runs
end-to-end under `agr eval --live`.

**Effort:** ~2–3 weeks. Spec+harness ~5 days; graphs ~1 day each with the generator.

---

### v3 — "Deep graphs" (AGR v1.2)

**Theme:** graphs that *search* and *learn* rather than execute a fixed path.

**Spec changes**

```yaml
- id: map
  fan_out: {over: shards, max: 40, on_partial: continue}   # NEW: G2 — real cardinality
- id: score
  aggregate: {op: quorum, n: 3, tie_break: judge}          # NEW: vote/median/quorum
- id: search
  kind: search                                             # NEW: branch/score/prune
  search: {branch: 4, depth: 3, score: "output.bench_ms", objective: min, prune: beam(2)}
memory:                                                    # NEW: G8
  scope: run | graph | org
  schema: ./state/lessons.schema.json
```

**New motifs:** `reflexion`, `tree-search`, `tournament`, `ensemble-quorum`,
`red-team-blue-team`, `blackboard`.

**Graphs (target ~20)**

| Graph | Domain | Motif |
|---|---|---|
| `architecture-decision-tournament` | software-engineering | tournament — k designs, pairwise judged bracket |
| `benchmark-driven-optimization-search` | software-engineering | tree-search — branch patches, beam-prune on benchmark |
| `prompt-graph-optimization` | research-knowledge | tree-search (AFlow) — self-optimizing graph, closes README's open item |
| `red-team-blue-team-hardening` | security | adversarial — attacker/defender alternate until attacker exhausts |
| `exploit-repro-and-patch` | security | reflexion — each failed repro writes a lesson |
| `self-healing-ci` | devops-sre | reflexion — flake diagnosis accumulates across runs |
| `forensic-investigation-blackboard` | security | blackboard — opportunistic agents on shared evidence |
| `differential-diagnosis-ensemble` | healthcare-science | ensemble-quorum — n independent, dissent surfaced |
| `portfolio-strategy-tournament` | finance | tournament + backtest scoring |
| `curriculum-designer` | education | reflexion — learner outcome feeds curriculum revision |
| …+10 across remaining orphans | | |

**Acceptance:** `fan_out` demonstrably executes n>1 shards in the harness;
≥5 graphs improve a measured score across iterations under `--live`;
red-team graph terminates with an evidence-of-absence artifact.

**Effort:** ~3–4 weeks. `fan_out` + `search` in the harness is the bulk.

---

### v4 — "Live graphs" (AGR v1.3)

**Theme:** always-on, durable, org-scale. Graphs stop being functions and become services.

**Spec changes**

```yaml
triggers:                                    # NEW: G9
  - {on: schedule, cron: "17 * * * *"}
  - {on: webhook, source: github, event: pull_request}
  - {on: signal, expr: "error_budget_burn > 2.0"}
durability:
  checkpoint: every_node
  resume: true
budget:                                      # NEW: G6, enforced
  usd_max: 5.00
  per_node: {model: auto, tier: cheapest_capable}
policy:
  requires_approval_for: [ability.risk == execute]
```

**New motifs:** `watch-loop`, `market/auction`, `federated-supervisor` (runtime
graph-of-graphs across repos/tenants), `simulation`.

**Graphs (target ~18)**

| Graph | Domain | Shape |
|---|---|---|
| `repo-maintainer-daemon` | software-engineering | watch-loop — deps, flakes, docs drift, opens PRs |
| `slo-guardian` | devops-sre | watch-loop on error-budget burn → auto-mitigate → escalate |
| `continuous-compliance-evidence` | legal-compliance | watch-loop — collects evidence continuously, not at audit time |
| `fleet-migration-supervisor` | software-engineering | federated-supervisor — one migration across N repos |
| `supplier-risk-monitor` | logistics-retail | watch-loop + market signals |
| `capacity-forecaster` | devops-sre | simulation — forecast, act, compare to actual, recalibrate |
| `cost-auction-router` | research-knowledge | market — bidders quote cost+confidence, allocator awards |
| `org-knowledge-consolidator` | business-ops | long-horizon memory, `scope: org` |
| …+10 | | |

**Acceptance:** a graph survives process restart mid-run and resumes;
budget cap actually halts a run; `repo-maintainer-daemon` runs 7 days unattended
against this repo and its PRs are reviewable.

**Effort:** ~4–6 weeks. Durability is the hard part.

---

## 4. Sequencing rationale

1. **v2 first** because every deeper pattern needs joins and I/O contracts. Building
   tree-search on top of accidental frontier-dedupe joins would be building on sand.
2. **v3 second** because search/learning needs real fan-out, which v2's typed state
   makes tractable.
3. **v4 last** because durability only pays once graphs are long enough to be worth
   resuming.

## 5. Cross-cutting work (every version)

- Generator (`scripts/gen_graphs.py`) grows from 8 hardcoded templates to a composable
  motif library — otherwise graph count scales linearly with hand-authoring effort.
- Eval cases must grow with node count; a 14-node lifecycle needs phase-level fixtures.
- `CARDS.md` / graph-of-graphs mermaid regeneration must handle nested subgraphs.
- Keep the audit-gated catalog invariant: every new graph graduates from a catalog entry.

## 6. Target end state

| | today | v2 | v3 | v4 |
|---|---|---|---|---|
| Graphs | 52 | ~74 | ~94 | ~112 |
| Motifs | 8 | 13 | 19 | 23 |
| Mean nodes/graph | 3.2 | ~6 | ~7 | ~8 |
| Catalog entries with a graph | 52/114 | 74/114 | 94/114 | 112/114 |
| Graphs with executable verification | 1 | ~25 | ~45 | ~70 |
