# Remediation plan for the 2026-09-12 audit

Source: [audit-gaps-2026-09-12.md](audit-gaps-2026-09-12.md), 17 findings, branch
`audit-remediation` @ `f14cfe1`. Same conventions as the
[2026-09-04 plan](audit-gaps-remediation-2026-09-04.md): every item has an owner
action, a phase, what it depends on, and what it unblocks. Four findings need a
human decision before work starts; they are **DECIDE** and listed first.

Reading order: §1 decisions · §2 one new finding found while planning · §3 phase
sequence · §4 dependency graph · §5 the full table · §6 what "done" means per
phase · §7 what this plan deliberately does not do.

Effort: S ≈ ½ day, M ≈ 2 days, L ≈ 1 week. Total **7×S + 8×M + 3×L**.

---

## 1. Decisions that gate work (make these first)

**Decided 2026-09-12 by the owner: Q1-Q4 all as recommended.** Execution order is
therefore Phase 0 on `main` immediately after PR #10 merges, Phases 1-3 in
sequence, Phase 4 once P2-02 lands, Phase 5 scoped to the 18 unsatisfiable
graphs, Phase 6 last.

## Status 2026-09-12: phases 0-6 landed, except P5-02

PR #10 merged (63 commits), then #11 (phases 0-3) and #12 (phases 4-5); phase 6
on `remediation-2026-09-12-phase6`. 637 tests, 91.9% coverage, `make check`
clean. Five things were found on the way that the audit had not seen, each
because the fix was actually executed rather than described:

- **The daemon restart did not restart anything.** The plist ran `uv run agr mcp`,
  which forks a child python, so `kickstart -k` killed the `uv` parent and
  orphaned the child to pid 1 — deaf to SIGTERM, needing SIGKILL. The process
  found alive from 9 Aug was one of these, meaning a restart had probably already
  been attempted and had reported success. launchd execs the venv binary now.
- **`publish.yml` asserted the wheel held 52 graphs**, against a registry of 83.
  The job only runs on a tag push and no tag had been pushed since `v0.1.1`, so
  the gate had been failing unobserved. **A3 "never released" was a bug, not a
  decision** — which is why Q3 was answered by fixing one line.
- **Every emitted graph with a fan_out or a join raised at runtime.**
  `StateGraph(dict)` gives LangGraph an unannotated `__root__` that refuses two
  writes in one superstep: 25 fan_out and 9 join graphs compiled cleanly and died
  with `InvalidUpdateError`. Found by P5-01 on its first run, which is what that
  item was for.
- **Six composites fan out over a key nothing produces.** The mock harness runs
  the map node once on an empty list and scores 1.0; the export sends zero shards
  and halts. v1.9's finding one level down — a node declaring an output whose
  fixture produces something else.
- **A steered run overwrote the graph's checked-in profile.** `agr goal` has
  passed a goal override since v1.7 with `write` at its default.

**Deviations from the plan, each deliberate:**

- **P5-03 was pulled forward into Phase 1.** It is the same file as P1-02 and the
  same failure: the plist carried no `EnvironmentVariables` at all, which turned
  off `bearer_guard` *and* made `run_graph(live=True)` permanently refuse.
- **P4-01 keeps both models** (Q2 as recommended) — the intersection stopped
  leading, the per-model row and the 5/60/18/0 cross-tab lead instead.
- **P6-02 tests core + the `mcp` extra, not `--all-extras`.** `crewai` pulls
  `onnxruntime`, which has no cp310 wheel, so `uv sync --all-extras` cannot
  resolve on 3.10. The package supports 3.10 (608 tests pass there) and the
  adapters extra needs 3.11+; both facts are now written down.
- **P6-01 applied the six dependabot bumps directly** rather than merging six PRs
  against a main that had moved 65 commits. `mcp` 2.x changes how a tool's
  exception surfaces (wrapped, reason on `__cause__`), which the autonomy refusal
  test now handles on either major.

**Still open: P5-02** — sourcing real fixtures for the 18 graphs no model
satisfies. It needs ~120 live episodes against a real endpoint, which is the one
part of this plan a checkout cannot do for itself.

| # | Finding | Question | Recommended | If chosen, unlocks |
|---|---|---|---|---|
| **Q1** | A2 | Merge PR #10 to `main` first and remediate there, or stack this plan onto `audit-remediation` and merge once? | **Merge #10 first.** It is 63 commits, green, and two days old; stacking 18 more items on an unmerged branch is the habit that produced a 63-commit backlog. Phase 0 then lands on `main` in hours. | Phases 1, 3 |
| **Q2** | B5 | The live headline: drop `qwen3.5:latest` (9.7B, passes 8%, separates nothing), keep it but stop leading with the intersection, or add a frontier model as a third arm? | **Keep two local models, stop publishing the intersection as the headline; add a frontier arm in Phase 4.** Dropping the small model loses the capability-gap/contract-problem split that is the column's whole purpose. The intersection is the part that misleads, not the model. | P4-01 |
| **Q3** | A3 | Release now (tag from the current tree), or pull the install/Beta claims until the fixtures are sourced? | **Release.** The blocker turned out to be a one-line bug (§2), not readiness. Shipping 0.10.0 with the honest live numbers is better than a live docs site pointing at a 404. | Phase 3 |
| **Q4** | B8 | Source real domain fixtures for all 83 graphs (L×3), or only for the 18 no model satisfies, and leave the rest authored-but-declared? | **The 18 first.** A contract no model satisfies is either a bad contract or starved data, and authored fixtures cannot tell those apart. The other 65 already pass on the 30B model; re-sourcing them buys confidence, not findings. | P5-02 |

---

## 2. One new finding, found while writing this plan

**P3-01 — `publish.yml` cannot succeed. This is why nothing has ever been released.**

```yaml
n=$(/tmp/verify/bin/agr list | wc -l)
test "$n" -eq 52
```

`agr list` returns **83**. The wheel-verification step has been asserting 52
since the registry had 52 graphs, so **every tag push fails before
`pypi-publish` runs**. Finding A3 ("never released") is not a decision anyone
made — it is a hardcoded constant that went stale 31 graphs ago and a workflow
nobody has been able to observe failing, because no tag has been pushed since
`v0.1.1`.

This converts A3 from an L to an S, and it is why Q3 recommends releasing.

---

## 3. Phase sequence

Phases are ordered by dependency, not importance. Each is mergeable on its own
and leaves `agr validate`, `pytest` and CI green.

| Phase | Goal | Items | Effort | Depends on |
|---|---|---|---|---|
| **0** | The staleness gate stops having a hole in it | P0-01..04 | 3×S + 1×M | nothing |
| **1** | What was built in the last five weeks is actually reachable | P1-01..04 | 3×S + 1×M | Q1 |
| **2** | Two small fixes that each currently defeat a whole layer | P2-01..02 | 2×M | Phase 1 |
| **3** | The package exists where the docs say it does | P3-01..04 | 2×S + 1×M | Q3, Phase 1 |
| **4** | The published numbers mean what a reader thinks they mean | P4-01..04 | 3×M + 1×L | Q2, Phase 0, P2-02 |
| **5** | The two places "quality-proven" is taken on trust | P5-01..03 | 1×S + 1×M + 2×L | Phase 2, Q4 |
| **6** | Hygiene | P6-01..03 | 2×S + 1×M | Phase 3 |

**Phase 0 is not optional and nothing should start before it.** Until the regen
gate is closed, any number this plan produces can silently go stale the same way
`live-coverage.md` did, and every later phase is measured against numbers the
gate does not check.

---

## 4. Dependency graph

```
Q1 ──> P1-01 (merge #10) ──┬──> Phase 2 ──> P2-02 ──┬──> P4-01 ──> P4-02/03
                           │                        │
                           ├──> Q3 ──> P3-01 ──> P3-03 ──> P3-04 ──> Phase 6
                           │
P0-01/02 ──> P0-03 ──> P0-04 ──────────────────────┘          Q4 ──> P5-02
                  (gate closed: every later number is checked)

P2-01 (version gates) ── independent, do early, blocks nothing but expires at v1.10
P5-01 (export round-trip) ── independent of everything; can run in parallel
```

---

## 5. The full table

### Phase 0 — close the regen hole

| # | Finding | Action | Effort | Done when |
|---|---|---|---|---|
| **P0-01** | B4 | Add `gen_breadth_report.py` and `gen_catalog.py` to the `regen` target in `Makefile` and to the regen block in `.github/workflows/ci.yml`. They are the only two `gen_*.py` scripts in neither. | S | `make regen` runs 11 generators, not 9 |
| **P0-02** | B4 | Add `docs/live-coverage.md` and `usecases/catalog.yaml` to the `clean-check` diff list in both `Makefile` and `ci.yml`. | S | `git diff --exit-code` covers both paths |
| **P0-03** | B4 | Regenerate and commit `docs/live-coverage.md`. It moves ✅38/🎲2/🚫19 across 4 models → ✅5/🎲1/🚫18 across 2, and 560 → 1150 held-not-counted. The 🚫 list changes membership on 11 of 18 rows, so this is a content correction, not a cosmetic one. | S | committed file matches a fresh regen |
| **P0-04** | B4 | **The actual fix:** a test that globs `scripts/gen_*.py` and asserts every one appears in the `Makefile` `regen` target, and that every path a generator writes appears in `clean-check`. A generator added in six months must not be able to reopen this hole. | M | `pytest -k regen_coverage` fails if a generator is added without wiring |

> Why P0-04 and not just P0-01: the repo already had this discipline — the
> Makefile's own header comment records that v1.1 shipped stale CARD.md files and
> that local pytest could not catch it. The response then was to add the
> generators to a list. Two generators were later added and not put on the list,
> and nothing noticed for months. A list that must be maintained by hand has
> already failed once here.

### Phase 1 — deploy what exists

| # | Finding | Action | Effort | Done when |
|---|---|---|---|---|
| **P1-01** | A2 | Merge PR #10 into `main` (63 commits, CI green since 10 Sep). | S | `git rev-list --count main...audit-remediation` → `0 0` |
| **P1-02** | A1 | Add `--restart` to `scripts/install_service.sh` (`launchctl kickstart -k gui/$(id -u)/<label>`), and make the installer always kickstart after writing the plist. | S | `scripts/install_service.sh --restart` cycles the daemon |
| **P1-03** | A1 | Expose the served revision: add the package version + `git rev-parse --short HEAD` to the MCP server's instructions string, or a `server_info` tool. A client must be able to tell it is talking to a 34-day-old process. | M | a client can read the served SHA without shelling out |
| **P1-04** | A1 | Restart the daemon and verify the tool list is 10, not 4: `validate_graph`, `run_graph`, `list_abilities`, `list_specialities`, `get_profile`, `diff_graphs` are reachable. | S | `tools/list` over MCP returns 10 |

> P1-03 is the durable half. Restarting fixes today; a served-revision field is
> what makes the next 34-day drift visible in one call. `KeepAlive: true` means
> the process will otherwise outlive any number of merges.

### Phase 2 — the two fixes that defeat a layer

| # | Finding | Action | Effort | Done when |
|---|---|---|---|---|
| **P2-01** | C10 | Replace the 12 string comparisons `doc["apiVersion"] < "agr/v1.8"` in `validate.py` (lines 292, 306, 386, 413, 506, 536, 574, 834, 870, …) with a parsed helper — `_apiver(doc) < (1, 8)` splitting on `/v` and `.` to an int tuple. Regression test: assert a graph at `agr/v1.10` is gated *on*, and assert `_apiver` orders `v1.9 < v1.10`. | M | `"agr/v1.10"` no longer sorts below `"agr/v1.8"` anywhere |
| **P2-02** | C9 | Thread `inputs` end to end: `case_inputs(case, goal=None, inputs=None)` overlays `inputs` onto the seed with the same override semantics `goal` already has; `eval_graph(..., inputs=None)` passes it down; `mcp_server.run_graph` passes its `inputs` argument instead of attaching a note; add `agr eval --inputs <json|@file>`. Test: a graph run with `inputs` sees them on the entry blackboard. | M | the note at `mcp_server.py:160` is deleted because the parameter works |

> P2-01 is latent, not live — but it is a one-line-per-site fix now and a silent
> disabling of eleven validation gates at the next bump. Do it while the reason
> is written down.
>
> P2-02 is the one that matters today. v1.9's entire finding is that goal-only
> invocation starves 71 of 83 graphs, and goal-only is currently the *only* way
> to run a graph through the MCP server — the interface the LaunchAgent exists to
> serve. The fix shipped; the API cannot reach it.

### Phase 3 — release

| # | Finding | Action | Effort | Done when |
|---|---|---|---|---|
| **P3-01** | §2 | Fix `publish.yml`'s `test "$n" -eq 52` — derive the expected count from the checkout (`find graphs -name graph.yaml \| wc -l`) and compare, so it can never go stale again. | S | the wheel step compares two computed numbers, not one constant |
| **P3-02** | §2 | Regression test asserting `publish.yml` contains no hardcoded registry count. | S | `pytest -k publish_gate` fails on a reintroduced literal |
| **P3-03** | A3 | Tag and publish. Version `0.10.0` (AGR v1.9 is the spec version, not the package version — keep them separate, they have diverged since `v0.1.1`). Verify `pypi.org/pypi/vitruvian-graphs/json` returns 200 and `uvx --from vitruvian-graphs agr list` returns 83. | M | the Documentation URL points at something installable |
| **P3-04** | A3 | Only after P3-03: README install section, Pages install snippet, and a GitHub Release with the v1.9 findings as its notes. | S | no published surface advertises an install that 404s |

### Phase 4 — make the published numbers mean what a reader thinks

| # | Finding | Action | Effort | Done when |
|---|---|---|---|---|
| **P4-01** | B5 | Retire "✅ N satisfied on every model" as the headline (per Q2). Lead with the per-model table README already has — 113/138 (82%) on the 30B, 12/139 (8%) on the 9.7B — plus the cross-tab split: 5 both · 60 large-only (capability gap) · 17 neither (contract problem) · 0 small-only. Regenerate `gen_breadth_report.py` to emit that shape. | M | `live-coverage.md` and README lead with the same number, and it is not the intersection |
| **P4-02** | B6 | Label the scoreboard headline at point of use: "83/83 at 100%" must read as *mock*, since all 83 profiles are `runner: mock, provisional: true` and 61 sit at `assert-fixture` depth. README caveats it a paragraph later; move it into the sentence. | M | the mock qualifier and the number are in the same sentence |
| **P4-03** | B7 | Surface `tier_moved` (19 graphs whose published tier depends on recordings the audit marks not-comparable) in `live-coverage.md`, not only inside `reports/a4-stale-recordings.json`. | M | the 19 are visible without parsing a 482KB JSON |
| **P4-04** | C11 | Optimizer gate 2: (a) refuse content-shaped mutations outright rather than passing them vacuously — replay reuses recorded output, so anything changing what a node is *told* replays identically (`mutate.py:77`); (b) change `if score < baseline` to require strict improvement, or gate neutral mutations behind an explicit flag, so 81 applied optimizations cannot drift the registry with no measured gain. | L | a content mutation is rejected with "cannot be gated by replay", not accepted |

> P4-04's (a) is the same class of bug v1.9 already fixed once: the optimizer was
> hill-climbing a constant because its gate could not distinguish two graphs.
> Gate 2 fixed that for structure and left the identical blind spot for content.

### Phase 5 — the two trust gaps

| # | Finding | Action | Effort | Done when |
|---|---|---|---|---|
| **P5-01** | C12 | Round-trip the exports. `tests/test_adapters.py` only asserts the emitted source *compiles*. Execute an emitted LangGraph with stub node functions that echo their declared outputs, and assert the resulting route matches the AGR mock trace — one graph per topology family (linear, router, fan-out, join, subgraph, human gate, saga/compensate). | M | `instantiate` is behaviour-tested, not syntax-tested |
| **P5-02** | B8 | Source real fixtures for the 18 graphs no model satisfies (per Q4). For each: source domain data, re-record, and classify the result as *contract problem* (still fails on real data) or *fixture artefact* (passes). This is the only way to tell those apart, and it is the direct successor to the v1.9 finding. | L | each of the 18 carries a sourced fixture and a classified verdict |
| **P5-03** | C13 | Have `install_service.sh` generate an `AGR_MCP_TOKEN` and write it into the plist's `EnvironmentVariables`. Today the plist has no `EnvironmentVariables` key at all, so `bearer_guard` is never installed **and** `run_graph(live=True)` is permanently refused — the guard is off and the feature it guards is unreachable, from the same missing variable. | S | the daemon rejects an unauthenticated request and accepts a live run |

> Sizing P5-02: a full 2-model re-record is ~550 episodes; at ~6 nodes and the
> measured 15.2s p50 for `qwen3-coder:30b` that is ~14h serial, and Ollama.app
> caps at one slot — a hand-run `ollama serve` with more slots is the difference
> between a day and a week. The 18-graph subset is ~120 episodes, well under a
> day. This is a second reason Q4 recommends the subset.

### Phase 6 — hygiene

| # | Finding | Action | Effort | Done when |
|---|---|---|---|---|
| **P6-01** | D15 | Clear 6 dependabot PRs open since 31 Aug. `mcp 1.28.1 → 2.1.1` is a **major** bump of the SDK the server is built on — merge it last, behind a `tools/list` smoke test against the running daemon. The 4 actions bumps are trivial. | M | dependabot queue is empty and the daemon still answers `tools/list` |
| **P6-02** | D16 | Add a Python matrix to `ci.yml`. `pyproject` claims 3.10–3.13 and `requires-python = ">=3.10"`; CI runs one interpreter and the local venv is 3.14.6, so the support claim has never been exercised. Either test the matrix or narrow the claim. | S | the classifiers and the matrix agree |
| **P6-03** | C14 | Surface the 48 of 131 catalogued use cases with no graph (63% coverage). Now gated by P0-01, so the number stops being invisible. | S | the gap is in a generated, diffed report |

---

## 6. What "done" means per phase

- **Phase 0** — `make regen && git diff --exit-code` is clean, and adding a new
  `scripts/gen_*.py` without wiring it fails the suite.
- **Phase 1** — `main` and `audit-remediation` are identical, and an MCP
  `tools/list` against 127.0.0.1:8765 returns 10 tools and a served SHA equal to
  `main`'s HEAD.
- **Phase 2** — a graph can be run over MCP with real `inputs`, and a
  synthetic `agr/v1.10` graph is validated by every gate a v1.9 graph is.
- **Phase 3** — `uvx --from vitruvian-graphs agr list` returns 83 lines on a
  clean machine.
- **Phase 4** — the headline live number in README, `live-coverage.md` and the
  Pages site is the same number, and it is not an intersection dominated by the
  weakest model.
- **Phase 5** — one emitted LangGraph is proven to route like its AGR source,
  and each of the 18 unsatisfiable graphs is labelled contract-problem or
  fixture-artefact on sourced data.
- **Phase 6** — CI tests the Python versions the package claims, and the
  dependabot queue is empty.

---

## 7. What this plan deliberately does not do

- **No LLM refiner (L3).** The v1.9 guidance A/B failed its pre-registered
  criteria (mean delta −0.125, 0 of 8 improved, one 6/6→0/6 regression), and
  `docs/agr-v1.9.md` records why: procedural prose competes with a contract that
  already expresses the procedure. Nothing in this audit changes that.
- **No re-record of the 65 graphs that already pass on the 30B model** (Q4).
  Re-sourcing them buys confidence, not findings.
- **No mypy `--strict` adoption.** `pyproject.toml` records the reasoning — a
  checker that fails on 400 pre-existing findings gets switched off. Noted in the
  audit as D17, not a finding.
- **No `parallel_group` execution work.** Deferred by Q2 of the 2026-09-04 plan
  and still correctly deferred; the runtime is documented as serial.
