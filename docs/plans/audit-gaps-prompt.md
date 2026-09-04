# Audit prompt: what is missing from agenticgraphs

Paste everything below the line into a fresh agent session opened at the repo root.

---

You are auditing `agenticgraphs` (`~/Projects/agenticgraphs`), a registry of
framework-neutral multi-agent workflow graphs in the AGR v1.8 YAML format, served
over MCP (`agr mcp --http --port 8765`). Your job is to find **what is missing**:
features, checks, evidence, docs, and tests that the project's own thesis requires
but that do not exist yet. You are not here to restate known limits or to fix
anything. Read-only. Produce a report.

## Orientation (verify each claim before relying on it)

- `graphs/<category>/<name>/graph.yaml`: ~112 graph directories on disk, 83 in the
  registry, milestones text says 103 "declare". Reconcile these three numbers first;
  a count that drifts between README, docs and disk is itself a finding.
- `src/agenticgraphs/`: `validate.py` (1036 lines, the linter), `harness.py` (1395
  lines, the runtime/recorder), `registry.py`, `compose.py`, `subgraphs.py`,
  `adapters.py` (LangGraph, CrewAI), `bindings.py` (ability to MCP tool binding),
  `safeexpr.py` (assert evaluator), `mutate.py`, `autonomy.py`, `triggers.py`,
  `mcp_server.py` (4 tools: `search_graphs`, `get_graph`, `instantiate`,
  `infuse_ability` with a `persist` flag).
- `spec/` holds three JSON schemas (graph, ability, speciality). `abilities/` has
  32 ability YAMLs, `specialities/` the role YAMLs, `usecases/catalog.yaml` the
  use-case index, `docs/agr-v1.8.md` the current spec, `docs/milestones.md` the
  per-version record, `docs/contract-findings.md` the generated scoreboard.
- `tests/`: 345 test functions across 28 files. `scripts/`: ~20 derive/fix/record
  scripts. `reports/`: generated audit JSON.
- Three stated principles: verification is structural (schema-enforced),
  quality is measured not claimed (eval profile gates "shipped"), mutation is
  first-class (infuse abilities instead of forking YAML).

## Already known. Do NOT re-report these; report only what they leave uncovered.

- Live evidence base is superseded by v1.8 and not yet re-recorded.
- Median graph is 4 nodes; primitives are motif demonstrations, not production flows.
- Only 20 of 83 contracts have an executable `command:` check; the rest are asserts
  on the model's own output.
- Verdict variance: 20% of cells flip on qwen3-coder:30b, 51% on devstral:24b; 74
  cells are n=1; 13 cells never parse and silently shrink the denominator.
- Only small local models plus gpt-4o were recorded; nothing claimed about frontier.
- 5 graphs are satisfied by no model (listed in `docs/contract-findings.md`).
- Search/optimization graphs are tested against synthetic gradients.

## Audit dimensions. For each, ask "what would have to exist for the thesis to hold, and does it?"

1. **Spec vs enforcement.** Diff `docs/agr-v1.8.md` and `spec/*.schema.json` against
   what `validate.py` actually checks. List every spec MUST/SHOULD with no lint, and
   every lint with no spec sentence. Check: unbounded loops, verifier reachability,
   `state.inputs` producers, fan_out `on_partial` semantics, `retries` on
   non-idempotent abilities, `risk_surface` derivation (is `execute` computed or
   declared?), `when:` guards referencing keys no node outputs.
2. **Ability and speciality grounding.** For every ability in `abilities/`, is there
   a binding in `bindings.py`? For every speciality, is it used by at least one graph?
   Which abilities are declared by graphs but have no schema file, and vice versa?
   Which bindings are stubs that always succeed?
3. **Runtime and harness.** What does `harness.py` not do that a runtime must:
   timeouts per node, cost/token accounting, cancellation, resumption from a
   checkpoint, parallel-group execution (is `parallel_groups` actually run in
   parallel or serialized?), structured error taxonomy (stall vs refusal vs parse
   failure vs contract failure), trace persistence format and its stability across
   versions. Check `docs/traces/` against what the harness emits today.
4. **Composition.** For composites that `ref` a primitive: what happens when the
   referenced primitive changes its I/O contract? Is there a lint, a pinned version,
   or nothing? Can a subgraph's `goal.required` propagate? Are cycles across refs
   detected?
5. **Adapters.** For LangGraph and CrewAI output: what AGR features are silently
   dropped (verifier nodes, `when:` guards, fan_out limits, retries, termination
   contracts, `verification:`)? Is there a round-trip test? Which other targets does
   the README or roadmap imply that do not exist?
6. **Evidence pipeline integrity.** Trace one recording end to end:
   `scripts/record_live.py` to `graphs/*/live/` to `gen_contract_findings.py` to
   `docs/contract-findings.md`. Find: places a number can be changed by hand,
   stale-recording detection (`reports/a4-stale-recordings.json`: is it enforced or
   informational?), what invalidates a recording (graph edit? spec bump? model
   update?), whether the scoreboard can distinguish "never run" from "ran and
   failed", and whether `self-graded.json` findings are all closed.
7. **MCP surface and safety.** `infuse_ability(persist=True)` writes to disk from an
   unauthenticated localhost HTTP server; read `docs/autonomy.md` and `autonomy.py`
   and state exactly what gates it. Check `safeexpr.py` for the evaluator's
   allow-list versus what `assert:` strings in `graphs/` actually use (name every
   assert that would fail to evaluate or that reaches outside the allow-list). Check
   whether `command:` strings with `{placeholders}` are shell-interpolated. Note the
   v1.8 commit "close an RCE" and confirm the fix covers every entry point, not one.
   List MCP tools a consumer would expect that are absent (run/execute a graph,
   validate a graph, list abilities/specialities, get eval profile, diff two graphs).
8. **Tests.** Map the 28 test files to the modules above. Which modules have no
   test? Which tests assert on fixtures only and never touch a graph in `graphs/`?
   Is there a test that every registry graph validates, composes, adapts to both
   targets, and has a parseable contract? Is there a test for the counts in README?
9. **Docs and onboarding.** Follow README "Getting Started" literally on a clean
   checkout and record where it breaks or diverges. Note docs that describe versions
   below v1.8 without a superseded banner, and README claims (badges, counts, "19
   motifs", "22 composites", "52 primitives") that no script regenerates.
10. **Roadmap blind spots.** The roadmap lists three items. From everything above,
    name what a fourth, fifth and sixth item must be, and why the current three
    cannot be finished without them.

## Method

- Every finding cites `file:line` or a command whose output shows it. No finding
  from memory or from the README alone.
- Run, do not read: `make test` (or `uv run pytest -q`), `agr validate` over every
  graph, `agr instantiate` for both adapters on a sample of 10 graphs including all
  composites, and the count reconciliation from Orientation.
- If a check cannot be run, say so and mark the finding UNVERIFIED rather than
  dropping it.
- Do not modify files. Scratch output goes outside the repo.

## Output

`docs/plans/audit-gaps-<YYYY-MM-DD>.md` containing:

1. **Count reconciliation** table (README / docs / registry / disk).
2. **Findings table**: id, dimension (1-10), gap type (missing-feature /
   missing-lint / missing-evidence / missing-test / missing-doc / safety),
   severity (blocks-thesis / degrades-trust / hygiene), evidence, one-line fix
   shape, effort (S/M/L).
3. **Top 5 gaps**, each with: why the stated principles fail without it, and the
   smallest change that would close it.
4. **What was checked and found sound**, one line each, so the next audit does not
   repeat it.
5. **UNVERIFIED** list.

Order findings by severity, then by effort ascending. Target 25 to 40 findings.
A finding that restates a Known item scores zero.
