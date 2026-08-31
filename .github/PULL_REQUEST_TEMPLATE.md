## What changes

<!-- One paragraph. If this adds or edits a graph, say what it does that no existing graph does. -->

## The gate

```sh
make check
```

- [ ] `agr validate` passes
- [ ] `pytest -q` passes (coverage ≥ 90%)
- [ ] `ruff check .` and `mypy` pass
- [ ] generated docs regenerated and committed (`make regen`)

## For a new or changed graph

- [ ] It has a `verifier` node and a `termination.contract`
- [ ] Its contract is **not self-graded** — no assert reads a flag the verifier node
      writes itself. Assert on a fact an upstream node produced, or add a
      `verification[].command`
- [ ] It declares a `goal` naming what the **caller** supplies (never what the graph produces)
- [ ] Golden cases in `cases.yaml` cover every branch
- [ ] Its topology differs from every existing graph — see `reports/clones.json`
