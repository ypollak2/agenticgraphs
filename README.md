# agenticgraphs

**A library of evolvable, quality-proven agentic graphs — for frameworks, developers, and agents themselves.**

Every framework has its own graph format. Nobody ships a registry of *ready-made, measured* workflows
that a running agent can discover, instantiate, and **mutate** — grafting new abilities into the
structure at runtime. That's this repo.

## North star

Help users **and agents** assemble top-quality agentic graphs for working together — where quality is
*measured, not claimed* (every graph carries an eval profile), and where the structure itself
(nodes, edges, abilities) can be changed and re-infused at any time.

Grounded in research: [GPTSwarm](https://proceedings.mlr.press/v235/zhuge24a.html) (agents as
optimizable graphs, ICML 2024) and [AFlow](https://openreview.net/forum?id=z5uVAKwmjf) (MCTS over
workflow space, ICLR 2025) show graph structure is a *searchable, improvable artifact* — often
letting smaller models beat larger ones at a fraction of the cost.

## Quickstart

```bash
uv run agr list                 # browse the registry
uv run agr search review        # find graphs
uv run agr validate             # schema + structural lint (MAST failure-mode checks)
```

## Anatomy

- `spec/` — AGR v1 JSON Schemas (graph, speciality, ability)
- `graphs/<category>/<name>/graph.yaml` — the library
- `specialities/` — roles a node can play, with required abilities
- `abilities/` — atomic capabilities, MCP-bindable
- Coming next (see plan): eval harness + `profile.json` per graph, `mutate/` (infuse/optimize),
  LangGraph adapter, MCP server so agents can `search / get / instantiate / infuse_ability`.

## Design rules

1. **No graph ships without a measured profile** — quality, cost, robustness, coordination overhead.
2. **Verification is structural** — verifier nodes and termination contracts are required by the spec.
3. **Mutation is first-class** — abilities are infused programmatically, not fork-and-edited.

MIT licensed.
