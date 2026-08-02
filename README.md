<a id="readme-top"></a>

<div align="center">

[![Graphs][graphs-shield]][graphs-url]
[![Use Cases][usecases-shield]][usecases-url]
[![Domains][domains-shield]][usecases-url]
[![Patterns][patterns-shield]][patterns-url]
[![Tests][tests-shield]][tests-url]
[![MIT License][license-shield]][license-url]

<br />

# 🕸️ agenticgraphs

**Evolvable, quality-proven agentic graphs — for frameworks, developers, and agents themselves.**

*LangGraph gives you a graph engine. CrewAI gives you a team abstraction.*
***Nobody gives you the graphs.*** *This repo is the missing library.*

<br />

[**Explore the graphs »**](graphs/)

[Browse Use Cases](usecases/catalog.yaml) · [Report Bug][issues-url] · [Request Graph][issues-url]

</div>

<details>
  <summary>📖 Table of Contents</summary>
  <ol>
    <li><a href="#-about-the-project">About The Project</a>
      <ul>
        <li><a href="#show-me-a-graph">Show Me a Graph</a></li>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li><a href="#-getting-started">Getting Started</a></li>
    <li><a href="#-usage">Usage</a>
      <ul>
        <li><a href="#concepts">Concepts</a></li>
        <li><a href="#the-eight-patterns">The Eight Patterns</a></li>
        <li><a href="#the-library-at-a-glance">The Library at a Glance</a></li>
      </ul>
    </li>
    <li><a href="#-roadmap">Roadmap</a></li>
    <li><a href="#-for-agents">For Agents</a></li>
    <li><a href="#-contributing">Contributing</a></li>
    <li><a href="#-license">License</a></li>
    <li><a href="#-contact">Contact</a></li>
    <li><a href="#-acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

---

## 🧭 About The Project

A **registry of ready-made multi-agent workflow graphs** in a portable, framework-neutral
format (AGR v1), built on three principles:

```yaml
principles:
  - verification_is_structural:   # verifier nodes, termination contracts, and machine-checkable
      enforced_by: the schema     # assertions are REQUIRED by the spec — not by convention
  - quality_is_measured_not_claimed:
      rule: graphs graduate to "shipped" only with an eval profile   # quality, cost, robustness
  - mutation_is_first_class:
      how: nodes declare specialities (roles) requiring abilities (atomic, MCP-bindable
           capabilities) — agents infuse new abilities instead of forking YAML
```

Grounded in research showing graph structure is a *searchable, improvable artifact*:
[GPTSwarm][gptswarm-url] (ICML 2024) treats agent swarms as optimizable graphs;
[AFlow][aflow-url] (ICLR 2025) searches workflow space with MCTS and often lets smaller
models beat larger ones on cost. Our structural lint encodes the [MAST][mast-url]
multi-agent failure taxonomy — dangling edges, unreachable nodes, unbounded loops,
verifier-free termination.

### Show Me a Graph

`graphs/software-engineering/code-review-pipeline/graph.yaml`:

```mermaid
flowchart LR
    T[triage<br/><i>code-triage</i>] -->|risk >= medium| S[security-review<br/><i>security-auditor</i>]
    T --> Y[style-review<br/><i>style-reviewer</i>]
    S --> V{{synthesize<br/><i>tech-lead · verifier</i>}}
    Y --> V
```

```yaml
apiVersion: agr/v1
name: code-review-pipeline
category: software-engineering
nodes:
  - id: security-review
    speciality: security-auditor            # a role...
    abilities: [read_diff, sast_scan, secret_detection]   # ...with required, bindable abilities
    parallel_group: reviews
  # ...
termination:
  max_steps: 12
  contract: "synthesize emits a verdict in {approve, request_changes} with every finding carrying file+line"
verification:
  - assert: "output.verdict in ['approve','request_changes']"
  - assert: "all(f.file and f.line for f in output.findings)"
```

No prose promises: the contract is part of the artifact, and `agr validate` rejects any graph
whose verifier is missing, whose loop has no exit condition, or whose node claims a speciality
it lacks the abilities for.

### Built With

[![Python][python-badge]][python-url]
[![uv][uv-badge]][uv-url]
[![JSON Schema][jsonschema-badge]][jsonschema-url]
[![YAML][yaml-badge]][yaml-url]
[![pytest][pytest-badge]][pytest-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## 🚀 Getting Started

### Prerequisites

* Python ≥ 3.10
* [uv][uv-url]
  ```sh
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

### Installation

1. Clone the repo
   ```sh
   git clone https://github.com/yalipollak/agenticgraphs.git && cd agenticgraphs
   ```
2. Install dependencies
   ```sh
   uv sync
   ```
3. Verify everything
   ```sh
   uv run agr validate && uv run pytest -q
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## 🧰 Usage

```sh
uv run agr list                # browse all 52 graphs
uv run agr search triage      # find graphs by keyword
uv run agr validate           # full registry: JSON Schema + MAST structural lint
```

Every number in this README is checkable:

```sh
uv run agr list | wc -l                      # 52 graphs
uv run python scripts/audit_usecases.py      # 112 use cases, 15 domains, AUDIT PASSED
```

### Concepts

| Concept | Lives in | What it is |
|---|---|---|
| **Graph** | `graphs/<domain>/<name>/graph.yaml` | Nodes + edges + termination contract + verification asserts |
| **Speciality** | `specialities/*.yaml` | A role a node plays (e.g. `security-auditor`), with required abilities |
| **Ability** | `abilities/*.yaml` | An atomic capability (e.g. `sast_scan`) with a risk level; MCP-bindable |
| **Use case** | `usecases/catalog.yaml` | Demand-side backlog: 112 audited entries that graduate into graphs |
| **Spec** | `spec/*.schema.json` | AGR v1 JSON Schemas for all of the above |

### The Eight Patterns

| Pattern | Shape | Canonical example |
|---|---|---|
| `pipeline` | staged hand-offs with a reviewing verifier | `contract-redline-pipeline` |
| `parallel-swarm` | planner fans out isolated workers; verifier gates merge | `verifier-swarm` |
| `router` | dispatcher sends work down the cheapest capable branch | `incident-triage-router` |
| `generator-critic` | producer/critic loop; critic can reject N times | `quiz-generation-verified` |
| `debate` | opposing advocates, judge synthesizes | `ab-test-analysis` |
| `map-reduce` | partition → parallel map → verified reduce | `release-notes-generation` |
| `planner-executor-verifier` | plan, execute with effects, prove post-conditions | `runbook-executor` |
| `loop` | attempt → measure → retry until target or budget | `performance-optimization` |

### The Library at a Glance

52 graphs across all 15 domains: software-engineering (8), devops-sre (6),
research-knowledge (5), data-analytics (5), security (4), and 3 each for content-marketing,
business-ops, finance, legal-compliance, healthcare-science, education,
customer-support-sales — plus hr-people, logistics-retail, creative-production.
Behind them, a [112-entry use-case catalog](usecases/catalog.yaml) whose invariants
(≥100 entries, ≥10 domains, unique ids, a verification clause on *every* entry) are
enforced by an executable audit wired into pytest.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## 🗺️ Roadmap

- [x] **M0** — AGR v1 spec, validator + MAST lint, `agr` CLI, 52 validating graphs, audit-gated 112-entry catalog
- [ ] **M1** — eval harness + `profile.json` per graph *(until then: structurally proven, not performance-measured)*
- [ ] **M2** — `mutate/`: infuse abilities, optimize structure (AFlow-style search)
- [ ] **M3** — adapters (LangGraph first) + MCP server: `search / get / instantiate / infuse_ability`

Three graphs are handcrafted with domain specialities (`code-review-pipeline`,
`verifier-swarm`, `cost-routed-research`); the other 49 are pattern-template instantiations
carrying real per-use-case contracts — deliberately generic until M1 measurement tells us
where specialization pays.

See [open issues][issues-url] for the full list of proposed graphs and known issues.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## 🤖 For Agents

You are a target audience of this repo. Today: clone it, `agr search <task>`, load the YAML,
map abilities onto your tools. After M3: an MCP server exposes the registry so you can discover,
instantiate, and mutate graphs at runtime — with each graph's measured profile telling you what
it's worth before you spend a token.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## 🤝 Contributing

A graph is accepted when — and only when — the gate passes: schema conformance, MAST lint,
resolvable specialities/abilities, and (post-M1) a measured profile.

1. Fork the project
2. Create your branch (`git checkout -b graph/amazing-workflow`)
3. Add your use case in `scripts/gen_catalog.py` (single source of truth) and regenerate
4. Run the gate (`uv run agr validate && uv run pytest`)
5. Commit (`git commit -m 'Add amazing-workflow graph'`)
6. Push and open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## 📄 License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## 📫 Contact

Yali Pollak — [@yalipollak](https://github.com/yalipollak)

Project Link: [https://github.com/yalipollak/agenticgraphs][repo-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>

## 🙏 Acknowledgments

* [GPTSwarm — agents as optimizable graphs (ICML 2024)][gptswarm-url]
* [AFlow — MCTS over workflow space (ICLR 2025)][aflow-url]
* [MAST — multi-agent failure taxonomy][mast-url]
* [Best-README-Template][best-readme-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES (reference style, per Best-README-Template) -->
[graphs-shield]: https://img.shields.io/badge/graphs-52-2ea44f?style=for-the-badge
[graphs-url]: graphs/
[usecases-shield]: https://img.shields.io/badge/use--case_catalog-112-2ea44f?style=for-the-badge
[usecases-url]: usecases/catalog.yaml
[domains-shield]: https://img.shields.io/badge/domains-15-2ea44f?style=for-the-badge
[patterns-shield]: https://img.shields.io/badge/patterns-8-2ea44f?style=for-the-badge
[patterns-url]: #the-eight-patterns
[tests-shield]: https://img.shields.io/badge/tests-8%2F8-blue?style=for-the-badge
[tests-url]: tests/
[license-shield]: https://img.shields.io/badge/license-MIT-blue?style=for-the-badge
[license-url]: LICENSE
[issues-url]: https://github.com/yalipollak/agenticgraphs/issues
[repo-url]: https://github.com/yalipollak/agenticgraphs
[gptswarm-url]: https://proceedings.mlr.press/v235/zhuge24a.html
[aflow-url]: https://openreview.net/forum?id=z5uVAKwmjf
[mast-url]: https://arxiv.org/abs/2503.13657
[best-readme-url]: https://github.com/othneildrew/Best-README-Template
[python-badge]: https://img.shields.io/badge/Python_3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white
[python-url]: https://www.python.org/
[uv-badge]: https://img.shields.io/badge/uv-DE5FE9?style=for-the-badge&logo=uv&logoColor=white
[uv-url]: https://docs.astral.sh/uv/
[jsonschema-badge]: https://img.shields.io/badge/JSON_Schema_2020--12-000000?style=for-the-badge&logo=json&logoColor=white
[jsonschema-url]: https://json-schema.org/
[yaml-badge]: https://img.shields.io/badge/YAML-CB171E?style=for-the-badge&logo=yaml&logoColor=white
[yaml-url]: https://yaml.org/
[pytest-badge]: https://img.shields.io/badge/pytest-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white
[pytest-url]: https://pytest.org/
