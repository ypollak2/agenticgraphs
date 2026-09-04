> **Superseded by [AGR v1.8](agr-v1.8.md).** This page describes an earlier version and is kept for the record; the current spec is agr-v1.8.md.

# AGR v1.3 — live

Additive over v1.2. Every v1, v1.1 and v1.2 graph validates and executes unchanged.

This document was written after the fact (2026-09-04 audit, D1-03): v1.3 shipped
with a plan and an audit but no spec page, so the rules it added were only
recoverable from schema `description` strings and linter docstrings. The facts
below come from `spec/agr-graph.schema.json`, `validate.py`, `harness.py`,
`triggers.py`, `CHANGELOG.md` §0.4.0 and `docs/milestones.md` M7.

## The rule this version adopted

**No field ships without an executing consumer in the same version.** v1.2's audit
found `state.schema` accepted-and-ignored for two versions, `memory` validated and
doing nothing, and `parallel_group` labelling parallelism that did not exist across
17 graphs — each passed schema, lint and tests. v1.3 applied the rule
retroactively and **deleted** `approval.timeout` and `retries.backoff`, which had
been accepted since v1.1 with nothing reading them.

## What v1.3 adds

### `triggers` — when a graph wants to run

```yaml
triggers:
  - on: schedule
    cron: "0 6 * * 1-5"
  - on: webhook
    source: github
    event: pull_request
  - on: signal
```

AGR declares; it does not schedule. `agr triggers <name> --target {cron,
github-actions,webhook}` emits the artifact the host already understands: crontab
lines, a workflow whose `on:` block mirrors the declared triggers, or a webhook
filter. A `signal` trigger that GitHub Actions cannot express is flagged in the
emitted output, never silently dropped (`triggers.py`).

### `durability` — a killed run can resume

```yaml
durability:
  checkpoint: every_node   # or never (default)
  resume: true
```

With `checkpoint: every_node` the run journals one record per executed node.
Resume is **replay** over v1.2 frames — no new state model, no storage engine:
`agr eval --resume-from <journal>` replays the journalled outputs, skips the nodes
they complete, and routes a resumed node through the same `_fire` path a fresh one
takes, so a resumed run cannot diverge from a live one by construction. The test
asserts trace *equality*. The journal record shape is specified in
[agr-v1.8.md](agr-v1.8.md#durability-and-the-journal).

### `budget` — enforced caps

```yaml
budget:
  usd_max: 0.50
  steps_max: 40
```

Checked **before** a node runs, not after it is recorded: a cap that lets the step
it forbids execute first is not a cap. `steps_max` halts on `rep.steps`; `usd_max`
halts on `_spend(runner, steps + 1)`, which is measured from the endpoint's token
usage when the model is priced and estimated otherwise. The report says which
(`usage.usd_measured`), and `budget_exhausted` names the cap that fired.

### The saga lint

A graph whose name ends in `-saga` must be able to undo itself: any node holding an
execute-risk ability needs a `kind: compensate` edge leaving it, and a graph
declaring the `saga` motif must have at least one compensate edge
(`validate.py`, `_lint_motif`). v1.8 generalised the property to every graph via
`_lint_irreversible`: a one-way effect (`file_record`, `cut_release`,
`shadow_write`, `backfill`) needs a compensating path whatever the graph calls
itself.

## Evidence

75 recordings, 25 graphs × 3 local models, checked in with failures included.
Per-model recordings (`<case>@<model>.json`), per-model pass rates, and
`models_disagree` / `fails_every_model` on `profile.json` date from here, as does
`docs/contract-findings.md`. The headline finding was that a large share of "model
failure" was harness brittleness in JSON extraction, and that only cross-model
disagreement separates a weak model from an unsatisfiable contract.

## Migration

None required. Graphs opt into `triggers`, `durability` and `budget` by declaring
them.

Plan: [v4-agr-1.3.md](plans/v4-agr-1.3.md) · Audit: [v4-audit.md](plans/v4-audit.md).
