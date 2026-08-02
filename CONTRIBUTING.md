# Contributing

## The gate

A contribution is accepted when — and only when — this passes locally and in CI:

```sh
uv run agr validate && uv run python scripts/audit_usecases.py && uv run pytest -q
```

No exceptions, no maintainer overrides. The gate *is* the review policy for structure;
humans review intent and taste.

## Adding a use case

1. Add one tuple to `E` in `scripts/gen_catalog.py` — the single source of truth.
2. `uv run python scripts/gen_catalog.py` to regenerate `usecases/catalog.yaml`.
3. The audit enforces: unique name, valid pattern, non-empty verification clause.

## Adding a graph

- **Generated**: add the use-case name to `TOP50` in `scripts/gen_graphs.py` and regenerate.
- **Handcrafted** (preferred for shipped graphs): write `graphs/<domain>/<name>/graph.yaml`
  against `spec/agr-graph.schema.json`. Every speciality/ability you reference must exist in
  `specialities/` / `abilities/` — add them if needed (kebab-case roles, snake_case abilities,
  risk level required).

## Rules that will not bend

1. Every graph has at least one `verifier` node and a `termination` contract.
2. Conditional back-edges only — no unbounded loops.
3. Verification clauses describe *executable* checks, not aspirations.
4. Post-M1: no graph ships without a measured `profile.json`.
