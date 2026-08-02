# Plan: 100+ Use-Case Catalog (research → plan → implementation → audit)

## Research (done)
- Session grounding: GPTSwarm (ICML 2024), AFlow (ICLR 2025) — graph structure is a
  searchable artifact; MAST taxonomy — failure modes the lint must catch.
- chuzom llm_research sweep (gpt-4o-mini, non-web, used as coverage checklist only):
  confirmed 13 core domains, flagged 3 missing — HR, logistics, retail. Adopted.
- Result: 15 domains, 8 graph patterns.

## Plan
**Entry schema** (`usecases/catalog.yaml`): `id` (uc-NNN), `name` (kebab), `domain`,
`pattern`, `summary`, `verification` (what an executable check would assert).

**Patterns**: pipeline, parallel-swarm, router, debate, map-reduce, generator-critic,
planner-executor-verifier, loop.

**Coverage targets (audit-enforced)**:
- >= 100 entries, unique ids and names
- >= 10 domains, >= 6 patterns actually used
- every entry has a non-empty verification clause (design rule 2: verification is structural)

**Graduation path**: catalog entry → `graphs/<category>/<name>/graph.yaml` (AGR v1) →
eval profile (M1). The catalog is the demand-side backlog; graphs are supply.

## Implementation
`usecases/catalog.yaml`, generated from `scripts/gen_catalog.py` (single source of truth,
regeneration is idempotent).

## Audit
`scripts/audit_usecases.py` — executable, exits non-zero on any violation; wired into
pytest (`tests/test_usecases.py`) so the gate runs in CI. No self-graded claims: the
count and coverage numbers in this doc are produced by the audit, not asserted by hand.
