# M11 — the registry core, agent types, and skills · M12 — 48 graphs in parallel

Four workstreams, split across two milestones because they are two different kinds
of work:

**M11 — code.** The registry stops being a loader and becomes a core that joins and
resolves: one authored bundle per artifact, one derived projection, **agent types
that the runtime actually reads**, and skills bound in both directions (graphs using
the skills a user already has in Claude Code or Codex; registry graphs published
back out as skills).

**M12 — content.** The 48 catalog entries with no graph, authored in parallel and
recorded.

The order matters and the split is the reason. Adding 48 graphs to today's registry
makes discovery worse and evidence thinner; adding skills without the join gives
them nowhere to be found; and every author writing into four shared generated files
is what makes "in parallel" a rebase queue rather than a merge. M12 is the only
workstream that gets cheaper, more grounded, and conflict-free for having waited.

Status: proposal. Measured against `a6f8464`, all numbers computed from the tree.
Architecture and the four decisions behind it: [architecture-m11.md](../architecture-m11.md).

---

## 1. Audit — what "the registry" is today

| Metric | Value |
|---|---|
| Graphs | **83** (15 domains, all at `agr/v1.7`) |
| Catalog entries | **131** — so **48 have no graph** |
| `registry.py` | **52 lines**: `glob`, `yaml.safe_load`, `SPEC_VERSION` |
| Full registry load | **74 ms** for 83 graphs |
| Search implementation | substring over `name + description + category` |
| Facts per graph, and where they live | **5 files, joined by nothing**: `graph.yaml`, `profile.json`, `lineage.yaml`, `evals/<name>/`, `usecases/catalog.yaml` |
| Live evidence | 83/83 recorded across 5 models |
| ✅ satisfied on every model, every sample | **13** |
| 🎲 flaky (one model both passed and failed) | **50** |
| ⚠️ models disagree | **15** |
| 🚫 satisfied by no model | **5** |
| Graphs with at least one **n=1** model cell | **48** |
| Node count vs. evidence | ✅ mean **3.1** nodes · 🎲 **3.8** · 🚫 **5.2** |

### 1.1 The finding

`registry.py` is a *loader*, not a registry. It answers "where are the files."
Everything that needs an actual registry — the CLI, the MCP server, three
generators, the catalog audit, `compose`, `mutate` — re-derives its own partial
view by globbing again. Three consequences, in descending order of cost:

**(a) The MCP surface hands agents graphs with no evidence attached.** The repo's
whole claim is *quality is measured, not claimed* — and `search_graphs` returns
`name / category / description / goal_required / structural`. It does not return
the pass rate, the model spread, the sample count, or the recording age. Every
one of those numbers already exists in `profile.json` and is already rendered in
the README scoreboard for humans. An agent asking for an incident-triage graph
gets `incident-triage-router` with no way to see it is 0/3 on one model and 3/3
on the other. The registry currently tells agents *less* than it tells readers.

**(b) Discovery is substring-only.** You cannot ask the registry for "a map-reduce
graph in finance, read-only risk surface, contract satisfied on every model,
n≥3." At 83 graphs a human can skim `CARDS.md`. At 131 that stops working, and
an agent never had the option.

**(c) Evidence is not pinned to the artifact it measured.** `ReplayRunner`
stamps the model and the date — not the graph revision. Edit a node's outputs and
the old recording still replays against the new topology, and the scoreboard
reports it as live evidence. This is the same class of gap M8 and M9 closed
(two vocabularies, nothing checking they match), and it becomes materially more
likely the moment several branches are editing graphs at once.

### 1.2 Why the expansion is blocked on it

Adding one graph today writes to **five shared files**: `README.md` (two generated
blocks), `CARDS.md`, `docs/traces/README.md`, `usecases/catalog.yaml`, and the
monolithic `E` list in `scripts/gen_catalog.py`. Two branches adding two unrelated
graphs conflict in all five. Twelve parallel authors is not a merge, it is a
rebase queue. Nothing about that is inherent — every one of those files is
*derived*, and the conflicts are in generated text.

Underneath that sits a build system nobody calls a build system: **14 Python files
in `scripts/`**, outside `src/`, absent from the wheel, uncovered by the test
suite, **six of which re-derive the same graph ↔ profile ↔ cases ↔ catalog join**.
The Makefile and CI each invoke three of them by name and then diff the tree.

### 1.3 The agent layer is config the runtime never reads

Looking for where an agent's configuration enters a run turned up nothing:

| Fact | Value |
|---|---|
| Speciality files | **34** |
| Fields any of them use | `name`, `description`, `requires_abilities`, `optional_abilities` |
| Declaring `prompt_seed` — in the schema since M0 | **0 of 34** |
| Runtime lines reading `prompt_seed` | **0** |
| Runtime lines opening `specialities/*.yaml` at all | **0** |
| What the model receives | `f"You are node '{id}' (speciality: {node['speciality']}) in a workflow."` |
| Node fields for persona, model, or tools | **none** — 310 nodes carry a bare string plus `abilities` |
| Consumers of `requires_abilities` | **1**, the linter, checking the name resolves |

The speciality file is never opened during a run. `researcher.yaml`'s description —
"Gathers and grounds facts from sources" — has never reached a model. `adapters.py`
emits `backstory="specialised in {speciality}"` because there is nothing else to
read.

This is the same shape as `binding`, which sat in the ability schema from M0 with
0 of 32 abilities using it, and the same shape as the gaps M8, M9 and M10 closed.
**agenticgraphs is graph-as-config with agent-as-*label*.** The agent layer is not
missing; it is declared, validated, and unwired — which makes this a fix rather
than a feature, and much cheaper than it looks.

---

## 2. Part A — the registry core

Seven pieces. None changes the AGR **graph** spec — every existing `graph.yaml`
stays valid at `agr/v1.7`. Two schemas below it do change, each versioned and
named where it happens (§C, §D).

### A0. The bundle and the projection — one rule

**Authored data is per-artifact; derived data is never committed by an author.**

*Bundle* (authored, one directory, zero shared files):

```
graphs/<domain>/<name>/
    graph.yaml
    usecase.yaml      # the catalog entry — moves out of scripts/gen_catalog.py's `E` list
    cases.yaml        # moves in from evals/<name>/          (decision 4.1)
    live/*.json       # moves in from evals/<name>/live/     (decision 4.1)
    CARD.md           # generated
    profile.json      # generated
```

*Projection* (derived, rebuilt, never hand-edited): `usecases/catalog.yaml`,
`CARDS.md`, every `CARD.md`, the two README blocks, `docs/traces/*`,
`docs/live-coverage.md`, `docs/contract-findings.md`, `registry.index.json`,
`profile.json`.

Adding a graph becomes **one directory**. Adding an ability or a skill becomes
**one file**. No shared file is touched, so N authors never collide — which is
what makes §D's parallel waves a merge instead of a queue.

The `evals/` → bundle move (decision 4.1) is a pure `git mv` of 83 directories,
with `registry` resolving the old path through a shim for one release, and
`README.md`, the wheel's `force-include`, and `record_live.py` updated to follow.

### A0b. `agr build` — the shadow build system comes inside

The six scripts that participate in the join — `gen_cards`, `gen_scoreboard`,
`gen_traces`, `gen_breadth_report`, `gen_contract_findings`, `audit_usecases`
(decision 4.3) — collapse into `src/agenticgraphs/build.py` behind **`agr build`**,
rendering every projection from `RegistryEntry`. They come inside the package,
under the test suite, and ship to contributors.

`gen_v2_graphs.py` / `gen_v3_graphs.py` stay where they are, as history.
`record_live.py` stays a recording tool. The Makefile and CI stop naming three
scripts and call one command, then diff exactly as they do now — the staleness
gate is unchanged, and `profile.json` stays excluded from it for the same reason
(it embeds today's date).

### A1. `RegistryEntry` — do the join once ✅ shipped

A dataclass in `registry.py` joining the five sources per graph:

```
identity    name, category, catalog id, motif/pattern, sha256(graph.yaml)
structure   structural_profile(doc)          # existing, moves behind the entry
contract    termination.contract, asserts, goal{required, description}
evidence    tier, per_model_pass_rate, samples_per_model, models, recorded, age_days
provenance  apiVersion, lineage mutations, has_cases, has_recordings
```

`Registry.load()` builds all 83 once (74 ms today — cache is not the point,
*one definition* is). `cli.py`, `mcp_server.py`, `inspect.py`, `validate.py`,
`mutate.py`, `evalcmd.py` and the new `build.py` become consumers. Net line count
should go **down**: six copies of this join exist today, all in `scripts/`.

The rule that makes it stick: **nothing above the registry core globs the
filesystem.** Today `inspect`, `validate`, `subgraphs`, `bindings`, `mutate`,
`evalcmd`, `mcp_server` and six scripts each do.

### A2. `registry.index.json` — one fetch, graded

Generated, checked in, gate-verified byte-stable alongside `CARD.md` (`profile.json`
stays excluded — it embeds today's date). Two jobs:

1. an agent or a web client reads the whole registry in one request instead of 83;
2. it carries the **evidence tier** — the thing search omits today.

The grade vocabulary already exists in `gen_scoreboard.py` (✅ 🚫 ⚠️ 🎲); the index
adds one more the scoreboard cannot express: **`unproven`** — a cell with n=1.
74 graph+model cells are n=1 today, and `docs/live-coverage.md` already says a
single sample cannot distinguish a graph that passes from one that passed by luck.

**Honesty constraint, non-negotiable:** the index makes no claim `profile.json`
does not already contain. It always carries `samples_per_model` and `models`
next to the tier, so "13 ✅" can never be read as "13 proven."

### A3. Faceted query — `agr find`, and the same facets on MCP

```
agr find --domain finance --motif map-reduce --risk read \
         --evidence satisfied-all --min-samples 3 --goal-required no
```

Same facets added to `search_graphs`, which keeps its `term` and gains a graded
result row. This is the single highest-value change for the "for agents" audience
and it is mostly plumbing on top of A1.

### A4. Pin evidence to the shape that produced it

Add `graph_sha` to each recording written by `scripts/record_live.py`, and to the
index. The gate then flags a recording whose `graph_sha` ≠ the current
`sha256(graph.yaml)` as **`stale-shape`** — reported, not silently replayed.

**Measured — [v13-a4-finding.md](v13-a4-finding.md), reproducible via
`scripts/audit_recordings.py`.** It is not zero:

- **71 of 560 recordings (13%)** replay against a graph shape that has since
  changed, and all 560 are counted in the published evidence.
- Staleness is **one cohort**: `qwen2.5-coder:7b` 30/30, `hermes3:8b` 23/23,
  `gpt-4o` 18/25 — and `devstral:24b` 0/235, `qwen3-coder:30b` 0/247. The two
  primary models were re-recorded; the other three never were.
- **The contract never moved** (0 graphs changed `verification`/`termination`).
  What moved is v1.5 node `outputs` (61 recordings) and v1.7 `goal`/`state` (26).
  So the failure mode is specific: a model never told which keys to return is
  graded against a key declaration that postdates its answer.
- **5 confirmed verdict flips** — same bytes, different verdict — and that is a
  floor: only 74 of 560 cells are single-sample and therefore comparable.
- **10 of 83 graphs have a published tier that depends on a stale recording.**
  Eight of the fifteen ⚠️ *models disagree* labels exist only because a stale
  recording disagreed.

Three consequences for this plan, folded in below: A4 is **blocking for M12**
rather than insurance; a **re-record of the 78 secondary-cohort recordings**
becomes a work item in its own right; and `shape_violations` — which is on
`RunReport` and dropped before serialisation — must reach `profile.json`, because
today a shape failure surfaces as `passed: false` with `assert_failures: []` and
nothing to explain it.

### A5. `agr new <name>` — scaffold one bundle

Writes the bundle from §A0 and nothing else: `graph.yaml` stamped from the use
case's motif, `usecase.yaml`, and a `cases.yaml` skeleton — then runs the gate
(schema, MAST lint, resolvable agent types and abilities, connected contract keys,
every node declaring). It writes **no projection**. `agr build` does that, once,
after merge.

`agr new --skill` and `agr new --ability` are the same shape one layer down: one
file, no registration step. A new ability today needs `abilities/<name>.yaml`
*plus* a builtin *plus* a `BUILTINS` entry *plus* a `SCHEMAS` entry in
`bindings.py`; under §C's provider chain and this scaffold, it needs the YAML.

---

## 3. Part B — agent types: wire the layer that already exists

§1.3 is the whole argument. 34 agent files, four fields, one of which reaches a
model as a bare substring. `prompt_seed` has been in the schema since M0 with no
reader and no writer.

### B1. The schema grows — *AGR Agent v1.1*

Same directory, same `speciality:` node key (decision 4.2): the concept is
promoted, not renamed, and 310 nodes already reference it.

```yaml
name: security-auditor
description: Finds exploitable defects and reports them with a location.
requires_abilities: [read_diff, sast_scan]
optional_abilities: [secret_detection]

prompt_seed: |                     # in the schema since M0 — this gives it a reader
  You look for defects an attacker could reach. Report severity and a file:line
  for every finding. A finding you cannot locate is not a finding.
skills: ["skill:security-review"]  # role-level skill binding, resolved per §C
model: {tier: reasoning}           # fast | balanced | reasoning — advisory (decision 4.4)
risk_ceiling: read                 # this role never executes, whatever a graph says
outputs: {findings: "list[{file:any, line:int, severity:any}]"}
```

No model name ever appears — a tier is a capability requirement, a model name
would be a vendor pin in a published artifact, and the runner may ignore the tier
entirely.

### B2. Resolution — `agents.py`, node → `ResolvedAgent`

Three precedence rules, written down so they cannot drift:

1. **Node overrides agent type overrides registry default** — persona, model, outputs.
2. **Abilities are a ceiling, never a grant.** The node's declared list bounds what
   resolves, whatever the role requires. A role requiring an ability the node did
   not declare is a **lint error**, not a silent grant. This is `bindings.py`'s
   bounded-toolbox property, preserved verbatim.
3. **Risk takes the minimum.** `risk_ceiling: read` on a role cannot be widened by
   a graph. Roles narrow; graphs never broaden.

`LLMRunner._prompt_text` and its sibling then build the prompt from the resolved
agent instead of interpolating a bare name.

### B3. What wiring it buys immediately

- `agr adapt --target crewai` stops emitting `backstory="specialised in
  {speciality}"`; `--target autogen` stops emitting `"You are a {speciality}
  agent"`. Both become the declared persona. The adapters were placeholders
  because there was nothing to read.
- One declaration compiles four ways: internal runner persona, CrewAI role,
  AutoGen system message, and — via §C.3 — a Claude Code subagent definition.
  **Config in, specialized agents out, in both directions.**
- 34 roles × a real persona is the cheapest quality lever in the registry, and it
  is measurable the same way everything else here is: re-record and compare.

**What must not be claimed:** wiring a persona is not evidence that it helps.
Given v12 — 20–51% of graph+model cells returning different verdicts on identical
input — a before/after on single samples would measure noise. If B3 claims a
quality effect at all, it does so at n≥3 per cell, or it says nothing.

---

## 4. Part C — skills, in both directions

### 4.0 Audit — the seam that already exists and is 91% empty

| Metric | Value |
|---|---|
| Abilities defined | **32** |
| Abilities with a `binding` block | **3** (`run_command`, `read_diff`, `web_search`) |
| `binding.kind` values the schema allows | `mcp_tool`, `shell`, `builtin` |
| `binding.kind` values anything implements | **`builtin` only** |
| Nodes across the registry | **310** |
| Nodes with ≥1 *bound* ability | **47 (15%)** |
| Most-used abilities, all unbound | `analyze` 56 · `generate` 51 · `critique` 37 · `decompose_goal` 19 · `execute_step` 19 |
| Harness artifacts the repo ships | **1**, hand-written (`.claude/commands/goal.md`) |

`bindings.py` says it plainly: the seam shipped in M0 and 0 of 32 abilities used
it. It is now 3 of 32, and each one cost a hand-written builtin. Writing 29 more
builtins to cover `analyze`, `critique`, `decompose_goal` is not the answer —
those are not tools, they are *procedures*, and a procedure written down for an
agent to follow is exactly what a skill is.

Meanwhile the user already has skills. This machine carries `~/.claude/skills/`
plus plugin skills and project `.claude/commands/`; Codex and other harnesses have
their own equivalents. The registry should be able to use them rather than
reimplement them.

### 4.1 Inbound — an ability can bind to a skill the user already has

Add `skill` to the `binding.kind` enum in `spec/agr-ability.schema.json`:

```yaml
name: analyze
description: Examine an artifact and report structured findings.
risk: read
binding:
  kind: skill
  ref: "skill:deep-analysis"      # resolved by the provider chain, harness-neutral
```

**Provider chain.** A `SkillProvider` interface with adapters, resolved in order
and reported by name so a run always says where a skill came from:

| Provider | Discovers |
|---|---|
| `claude-code` | `.claude/skills/*/SKILL.md`, `~/.claude/skills/*/SKILL.md`, plugin skills, `.claude/commands/*.md` |
| `codex` | the harness's prompt/skill directory and `AGENTS.md` procedures |
| `generic` | any directory of SKILL.md-shaped files (frontmatter `name` + `description`) |

Discovery reads frontmatter only — `name`, `description`, and the path. Nothing is
imported into the repo, nothing is copied, and the user's skill files are never
modified. `agr skills list` prints what resolved, from which provider, for which
ability.

**Bounded, on the existing principle.** `bindings.py` already refuses the open
toolbox: a node gets only what its `abilities` declare. Skills inherit that
exactly — `bind_for(node)` gains skill-backed entries, and a skill nothing binds
to is invisible to the graph. No node gains a capability it did not declare.

**Risk defaults to `execute`.** A skill is prose instructing an agent to run
commands; treating it as `read` because it looks like a document would be the
whole point of the risk model, missed. Skill-backed abilities are gated behind
the same opt-ins that already exist (`--allow-tools`, `AGR_AUTONOMOUS_ALLOW_EXECUTE`),
and an ability may declare a lower risk only explicitly, in its own YAML.

### 4.2 Two execution modes, graded differently — the honest part

`agr` cannot invoke a Claude Code skill. The harness is the executor. Pretending
otherwise is how a plan produces a feature that reports success and does nothing.
So there are two modes and they must not be reported as the same thing:

| Mode | What happens | Grade |
|---|---|---|
| **invoked** | The graph runs *inside* a harness (Claude Code driving `agr mcp`). The registry advertises which skills each node is entitled to; the harness invokes them and returns results, which land as `ToolCall` records on the existing grounded path. | `assert-grounded` is reachable |
| **advised** | No harness. The skill's body is injected as node context — a procedure the model is told to follow. Nothing executes. | **`skill-advised`, never grounded** |

This is the same distinction as `assert-fixture` vs `assert-live`, applied one
layer out, and it is the only reason the feature is worth shipping: the registry
already has 18 composite assert failures demanding a fact a model cannot invent.
A skill that is merely *read* does not produce that fact. A skill the harness
actually *ran* does.

### 4.3 Outbound — publish the registry as skills

The repo already has this pattern twice: `agr adapt` emits framework source,
`agr triggers` emits host artifacts, both self-contained, neither taking a runtime
dependency. Skills are the third:

```
agr skills emit --target claude-code   # → .claude/skills/<name>/SKILL.md
agr skills emit --target codex
```

**Do not emit one skill per graph.** 131 skills is context pollution and would
make the registry actively worse to live with. Emit **three**, backed by the
generated index from A2:

- `find-a-graph` — faceted search over the index, returning graded rows (§A3)
- `run-a-graph` — the goal-first run procedure that `.claude/commands/goal.md`
  is today, *generated* rather than hand-written, so it cannot drift from the
  registry it describes
- `contribute-a-graph` — the `agr new` ingest path and the gate (§A5)

The existing hand-written `goal.md` is the argument for generating them: it names
`search_graphs`, `goal_required`, `assert-fixture`, and `assert-grounded` — four
things this milestone changes. Hand-maintained harness artifacts go stale silently;
generated ones fail the staleness gate.

### 4.4 Skills as registry artifacts

Skills join graphs, specialities, and abilities as a first-class registry kind:
`spec/agr-skill.schema.json`, a `skills/` directory for registry-owned skills,
inclusion in `registry.index.json` (A2), a `--requires-skill` facet (A3), an MCP
`list_skills`, and a `force-include` entry so the wheel stays self-contained.

The ability schema change is the one spec touch in this milestone: adding `skill`
to a closed enum under `additionalProperties: false` is forward-compatible for
new validators and rejected by old ones. Call it AGR Ability v1.1 and say so,
rather than slipping an enum value into a v1 document.

### 4.5 What this buys the expansion

The 48 new graphs are the first ones that can be authored *with* skill-backed
abilities. `analyze` / `critique` / `decompose_goal` — the three most-used
abilities in the registry, all unbound today — are exactly the ones a user's
existing skills already implement. That is the difference between 48 more graphs
at fixture depth and 48 graphs that can reach grounded evidence when run inside a
harness the user already uses.

---

## 5. Part D — M12: 48 graphs, in parallel

### D0. De-conflicted by construction

Nothing to do here beyond §A0: the catalog entry lives in the bundle, the
projection is rebuilt by `agr build`, and no author writes a shared file. The
"split the `E` list per domain" half-measure an earlier draft proposed is
unnecessary once the entry lives with the graph it describes.

Authors stop committing generated text entirely. The staleness gate still fails
the build if CI's regeneration differs from the tree — unchanged.

### D1. The waves

The 48 uncovered entries, by domain — the natural parallel unit, one bundle per
graph and no shared file between them:

| Wave | Domains | Graphs |
|---|---|---|
| 1 | content-marketing 5 · research-knowledge 4 · finance 4 · education 4 | 17 |
| 2 | hr-people 4 · logistics-retail 4 · creative-production 4 · data-analytics 3 | 15 |
| 3 | legal-compliance 3 · healthcare-science 3 · customer-support-sales 3 | 9 |
| 4 | devops-sre 2 · business-ops 2 · security 2 · software-engineering 1 | 7 |

By motif: pipeline 12 · map-reduce 12 · generator-critic 9 ·
planner-executor-verifier 5 · parallel-swarm 5 · debate 3 · router 2.

One author (or agent, in its own worktree) per domain. The per-branch gate is
`agr validate` + `pytest` + `agr eval <name>`; only the merge runs `agr build`.

### D2. The evidence budget — the part that actually costs something

This is where the plan must be honest with itself. **The YAML is the cheap half.**
The v2 audit's verdict on the last expansion was that the library got *wide and
flat*; the current numbers add a second warning, that depth costs contract
quality — ✅ graphs average 3.1 nodes, 🚫 graphs average 5.2.

If 48 graphs ship at `assert-fixture` depth, the share of the registry carrying
real-model evidence goes 83/83 → 83/131 (63%), and the headline claim degrades
without a single false statement being made. Three options, in order of
preference:

1. **Record as you go** — ≥2 models × 3 samples per new graph. ~288 recordings.
   3 samples is the minimum honest number given v12: 20–51% of cells returned a
   different verdict on identical input, and 74 cells are still n=1. This keeps
   the registry's central claim intact. **Recommended.**
2. **Ship graded `unproven`** — graphs land with cases but no recordings, and A2's
   tier says so plainly in search results, the scoreboard, and every CARD. Cheap,
   honest, and it leaves a visible 48-graph debt.
3. **Ship at fixture depth without a tier** — reintroduces exactly the comfortable
   fiction `assert-fixture` was built to expose. Rejected.

Two existing debts fold into the same `record_live.py` run and should be paid
before the new graphs land, not after:

- **The 78 stale secondary-cohort recordings** (`qwen2.5-coder:7b`, `hermes3:8b`,
  `gpt-4o`) — re-recorded against current shapes. Until then, 8 of the 15
  ⚠️ *models disagree* labels are unattributable: a weak model and a model
  answering a question the graph no longer asks are indistinguishable in the
  current evidence. See [v13-a4-finding.md](v13-a4-finding.md).
- **The 74 n=1 cells** — resampled to n=3, retiring the largest caveat in the
  README's known-limits section.

Sequencing matters here: adding 48 graphs on top of a 13%-stale baseline compounds
the error rather than diluting it.

### D3. Guard against wide-and-flat

- Every new graph carries the domain-specific contract from its catalog entry's
  `verification` field — not the template's generic assert.
- Cap templated instantiation: at least one deliberately authored graph per wave,
  preferring the motifs the library is thin on (2 routers, 3 debates) over the
  24 more pipelines and map-reduces.
- The gate already refuses unconnected contract keys and silent nodes (v1.4/v1.5);
  no new lint needed, but stamping 48 graphs is the first real load test of both.
- New graphs are authored against **resolved agent types** (§B), so a role's
  persona and risk ceiling arrive with the template rather than after it.

---

## 6. Sequencing

**M11 — code.**

| Step | Ships | Depends on |
|---|---|---|
| A1 `RegistryEntry` + consumers migrated | one join instead of six | — |
| A0 bundle: `usecase.yaml` in, `evals/` folded in, shim | one directory per graph, zero shared files | A1 |
| A0b `agr build` absorbs the six join scripts | the build is package code, under test | A1, A0 |
| A4 `graph_sha` + `audit_recordings.py` in the gate + `shape_violations` serialised | staleness is detected, not reconstructed | A1 |
| A2 `registry.index.json` + `unproven` tier | agents can see evidence | A1 |
| A3 `agr find` + MCP facets | discovery survives 131 graphs | A2 |
| B1 *AGR Agent v1.1* schema + `prompt_seed` wired | 34 roles stop being labels | A1 |
| B2 `agents.py` resolution + precedence lint | node/role/risk rules cannot drift | B1 |
| B3 adapters read the real persona | `agr adapt` stops emitting placeholders | B2 |
| C1 `binding.kind: skill` + provider chain | 29 unbound abilities become reachable | A1, B2 |
| C2 invoked / advised grading | a skill run cannot be mistaken for a skill read | C1 |
| C3 `agr skills emit` (3 skills + subagent defs) | harness artifacts stop being hand-written | A2, B1, C1 |
| A5 `agr new` | one command per bundle | A0, A0b |

**M12 — content.**

| Step | Ships | Depends on |
|---|---|---|
| D0 re-record the 78 stale secondary-cohort recordings | an uncontaminated baseline | A4 |
| D1 waves 1–4 | 48 graphs | A5, C1, D0 |
| D2 recordings (~288) + resampling the 74 n=1 cells | the claim stays true | D1 |

A4 ran first, as planned, and did change what the expansion is allowed to claim:
13% of recordings are stale, 10 published tiers depend on them, and the re-record
(D0) is now a precondition for M12 rather than a cleanup after it. B2 lands before C1
because a skill binds through a resolved agent, and C1 lands before D1 so the new
graphs declare skill-backed abilities instead of being retrofitted.

**One-way doors, flagged:** the `evals/` move (A0) rewrites history-adjacent paths
and the shim expires; the ability-schema enum (C) and the agent-schema growth (B1)
are both closed-enum widenings that old validators reject. Everything else in M11
is internal and reversible.

## 7. Non-goals

- **No AGR graph spec bump.** Every existing `graph.yaml` stays valid at `agr/v1.7`,
  untouched. Two schemas below it grow, each versioned and named: the ability
  schema's `binding.kind` (§4.4) and the agent schema (§B1).
- **No renaming of `speciality`.** The concept is promoted in place (decision 4.2).
  310 node references stay as they are.
- **No model names in registry artifacts.** Agent types declare a tier; the runner
  may ignore it (decision 4.4).
- **No rewrite of the harness.** The scheduler, the trace lock, join/fan-out
  semantics and the gate are untouched. The runner's *prompt construction* changes;
  its *execution* does not.
- No remote/federated registry, no publish-and-install of third-party graphs.
- No skill marketplace, no shipping copies of users' skills, no writing to the
  user's skill directories except the artifacts `agr skills emit` generates.
- `agr` does not become a skill executor. Outside a harness, skills are advised
  and graded as advised.
- No search index engine. 74 ms is not a performance problem; the missing thing
  is *facets and grades*, not speed.
- No new claim about frontier models. The evidence stays what it is: small local
  models, 5 of them, sampled.

## 8. What would falsify this plan

- ~~If A4's measurement finds zero stale recordings, A4 is insurance rather than a
  fix.~~ **Resolved: 71 of 560 are stale and 10 published tiers depend on them.**
  A4 is a fix, and the re-record it implies (D0) is a precondition for M12.
- If the D0 re-record leaves all 8 unattributable disagreements exactly where they
  are, the staleness was real but inert, and the ⚠️ labels were measuring model
  weakness after all — which is worth knowing and worth saying plainly.
- If `agr build` does not come out **shorter** than the six scripts it replaces,
  the join was not actually duplicated and A1 bought structure without saving
  anything. Count the lines before and after and publish both.
- If wiring agent personas (§B) moves no graph's pass rate at n≥3, the layer was
  correctly wired and simply does not matter to these models — which is a real
  finding and belongs in the scoreboard, not in a silent revert. What it must not
  become is a quality claim rested on single samples; v12 already showed what that
  measures.
- If faceted search sees no use from either the CLI or the MCP client, A3 was
  scaffolding for a demand that does not exist, and the index (A2) was the value.
- If skill-backed abilities raise no graph above `assert-fixture` when run inside
  a real harness, the inbound half (C1/C2) delivered vocabulary, not grounding —
  and the honest response is to say so in the scoreboard, not to widen the enum.
- If the 48 new graphs land and the ✅ share falls below today's 13/83, M12 made
  the library wider and less proven — the exact outcome §D2 and §D3 exist to
  prevent, and the wave should stop rather than continue.
