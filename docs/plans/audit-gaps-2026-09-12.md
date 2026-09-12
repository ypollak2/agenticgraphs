# Audit — what is not working or missing (2026-09-12)

Scope: `audit-remediation` @ `f14cfe1`, plus the deployed MCP daemon and the
published surface (`main`, Pages, PyPI). Suite is green: 527 passed, 1 xfailed,
91.74% coverage, `make test` exit 0. Nothing below is a test failure — every
finding is something the gate cannot see.

Ranked by what it costs to leave alone.

---

## A. Nothing that was built in the last five weeks is actually in use

### A1 — The MCP daemon has served stale code for 34 days · **blocking**

`com.ypollak2.agenticgraphs-mcp` (pid 11317/11322) has been up since
**9 Aug 2026 22:13**. `KeepAlive` keeps it alive; nothing restarts it on a code
change. It is therefore serving `main`'s 4-tool server.

Six tools added on 4 Sep (`cdbff83`) are unreachable:
`validate_graph`, `run_graph`, `list_abilities`, `list_specialities`,
`get_profile`, `diff_graphs`.

Verified from the client side: an MCP session on this machine today lists exactly
`search_graphs`, `get_graph`, `instantiate`, `infuse_ability` — 4, not 10.

**Fix:** merge PR #10, then `launchctl kickstart -k gui/$(id -u)/com.ypollak2.agenticgraphs-mcp`.
Then add a restart step to `scripts/install_service.sh` so this cannot recur.

### A2 — `main` is 63 commits behind; the public repo advertises v1.8 · **blocking**

`git rev-list --left-right --count main...audit-remediation` → `0 63`.
PR #10 has been open since 10 Sep with CI green (run 34519251175, success).

Everything v1.9 found and fixed — fixture poverty, the optimizer hill-climbing a
constant, the guidance negative result — is invisible on the default branch.
`main`'s README still says `apiVersion: agr/v1.8` and **"38 of 83 satisfy their
contract on every model"**, a number the v1.9 re-record replaced with 5.

### A3 — The package has never been released · **high**

| claim | reality |
|---|---|
| `version = "0.9.4"` | only tag in the repo is `v0.1.1` |
| `Development Status :: 4 - Beta` | `gh release list` → empty |
| `publish.yml` holds `id-token: write` | `pypi.org/pypi/vitruvian-graphs/json` → **404** |
| Documentation URL live (HTTP 200) | documents an installable package that does not exist |

The docs site is the only shipped surface, and it points at an install that fails.

---

## B. The evidence disagrees with itself

### B4 — `docs/live-coverage.md` is stale by 7.6× and CI structurally cannot catch it · **high**

Committed file says **✅ 38 / 🎲 2 / 🚫 19** across 4 models.
Regenerating it (`scripts/gen_breadth_report.py`) on the current tree gives
**✅ 5 / 🎲 1 / 🚫 18** across 2 models, and 1150 held-but-not-counted recordings
rather than 560. `README.md:211` already says 5. Two documents in one repo differ
by 7.6× on the project's headline quality number.

Root cause is a hole in the staleness gate, not an oversight. `make regen` and
CI run nine generators and `clean-check` diffs eight paths. Two generators are in
neither list:

- `scripts/gen_breadth_report.py` → writes `docs/live-coverage.md`
- `scripts/gen_catalog.py` → writes `usecases/catalog.yaml`

And `docs/live-coverage.md` is not in the `clean-check` path list either. The
repo's whole anti-staleness discipline — built precisely because v1.1 shipped
stale CARD.md files — has a gap exactly where the flagship number lives.

**Fix:** add both scripts to `make regen` and the CI regen block, and add
`docs/live-coverage.md` + `usecases/catalog.yaml` to the `clean-check` diff list.
This is a ~4-line change and it is the highest-value fix in the audit.

### B5 — "satisfied on every model" measures the weakest model, not the registry · **high**

README's own cross-tab:

| | `qwen3-coder:30b` (30B) | `qwen3.5:latest` (9.7B) |
|---|---|---|
| contracts satisfied | 113 of 138 (**82%**) | 12 of 139 (**8%**) |

5 pass on both · 60 pass only on the larger · 17 fail on both · **0 pass only on
the smaller**.

Because the small model passes almost nothing and discriminates nothing, the ✅
intersection is essentially "what qwen3.5:latest can do". Publishing ✅5 as the
registry's quality figure understates it by ~20×, in the same way the pre-v1.9
goal-only cases overstated the model's failures. It is the mirror image of the
bug v1.9 just fixed.

**Fix:** either drop the 9.7B model from the baseline (it adds no separating
information) or stop leading with the intersection and report per-model with the
capability-gap / contract-problem split, which README already does well.

### B6 — The headline pass rate is 100% mock · **medium**

All 83 `profile.json` files: `runner: mock`, `provisional: true`.
Depth: `assert-fixture` 61, `command` 22. README caveats this clearly, but
"83/83 graphs at 100% pass rate" is still the number that leads, and
`assert-fixture` means the assert held against a fixture written alongside the
graph.

### B7 — 19 graphs' published tier rests on recordings the audit itself calls not-comparable · **medium**

`reports/a4-stale-recordings.json` → `tier_moved` has **19 entries**; 1428 rows
are `verdict: not-comparable`. Most moved graphs go `models-disagree` →
`unsatisfiable` once stale rows are dropped. The published tier is optimistic
for ~23% of the registry.

### B8 — The fixtures are authored, not sourced · **medium, carried forward**

Self-declared in `docs/agr-v1.9.md` "Known limits" and unresolved. A graph
passing on data written to fit its contract is soft evidence. This was the
natural next work after v1.9 and it has not started.

---

## C. Functional gaps in shipped code

### C9 — `run_graph`'s `inputs` parameter does nothing · **high**

`mcp_server.py:137` accepts `inputs: dict | None`, and the only thing it does
with it is attach `"inputs are supplied by the graph's golden cases; use goal to
set the subject"` to the result. So the sole way to run a graph over MCP is
goal-only — **precisely the invocation v1.9 proved starves 71 of 83 graphs.**
The fix that took 63 commits is not reachable through the API.

**Fix:** thread `inputs` into `case_inputs`, or delete the parameter. A declared
argument that is silently ignored is worse than an absent one.

### C10 — Version gates misorder at v1.10 · **high, latent**

Twelve sites in `validate.py` (292, 306, 386, 413, 506, 536, 574, 834, 870, …)
compare `doc["apiVersion"] < "agr/v1.8"` as **strings**.
`"agr/v1.10" < "agr/v1.8"` is `True`. At the next minor bump, every one of those
gates silently classifies new graphs as pre-1.8 and stops enforcing — a whole
validation tier turns off with no error. Documented as a known limit in
`agr-v1.9.md`; still not fixed. It is a one-line parse-and-compare-tuples fix
now and a silent correctness failure later.

### C11 — Optimizer gate 2 is vacuous for content mutations · **medium**

`mutate.py` gate 2 replays *recorded* model output against the mutated doc. As
documented at `mutate.py:77`, a mutation that changes what a node is *told*
replays identically — so the quality gate constrains structure only and cannot
see prompt, criteria or guidance changes. Separately, `if score < baseline`
accepts equal-scoring mutations, so the registry can drift under 81 applied
optimizations without any measured gain.

### C12 — Framework exports are never round-tripped · **medium**

`instantiate` is a shipped MCP tool, and `adapters.py` emits one
`NotImplementedError` stub per node. `tests/test_adapters.py` only asserts the
emitted source *compiles* (`compile(src, ..., "exec")`, "runnable-shaped: no
syntax errors"). Nothing anywhere checks that an exported LangGraph or CrewAI
graph routes like the AGR graph it came from. The primary consumer-facing output
of the project is untested for behaviour.

### C13 — The deployed MCP server runs unauthenticated · **medium**

The LaunchAgent plist sets no `EnvironmentVariables` at all, so `AGR_MCP_TOKEN`
is unset, `http_token()` returns `None`, and `bearer_guard` is never installed on
the HTTP app bound to 127.0.0.1:8765. Any local process can drive the registry.
Read-only-without-a-token is the intended posture, but the same missing token
also means `run_graph(live=True)` is permanently refused — the spend guard is off
in the only deployment that exists, and so is the feature it guards.

### C14 — 48 of 131 catalogued use cases have no graph · **low**

`gen_catalog.py` → "131 entries (48 still without a graph)". 63% coverage of the
project's own catalogue, and the number is not surfaced in any gated report
(see B4 — `gen_catalog.py` is one of the two ungated generators).

---

## D. Hygiene

- **D15 — 6 dependabot PRs open since 31 Aug**, including `mcp 1.28.1 → 2.1.1`,
  a **major** bump of the SDK the server is built on. A fresh `uv sync` without
  `--frozen` resolves toward it; nobody has run the server against it.
- **D16 — CI runs exactly one Python.** `pyproject` claims 3.10–3.13 and
  `requires-python = ">=3.10"`; `ci.yml` has no version matrix and mypy targets
  3.10 while the local venv is 3.14.6. The support matrix is asserted, never
  exercised.
- **D17 — mypy is deliberately non-strict.** Documented and defensible
  (`pyproject.toml`: "a type checker that fails on 400 pre-existing findings gets
  switched off"). Noted, not a finding.

---

## Recommended order

1. **B4** — close the regen/clean-check hole (~4 lines). Until this lands, every
   other number in the repo is unverifiable.
2. **A1 + A2** — merge PR #10 and restart the daemon. The work already exists;
   it is simply not deployed.
3. **C9, C10** — two small fixes, each of which currently defeats a whole layer
   (the v1.9 subject fix; the v1.8 validation tier).
4. **B5** — decide what the headline live number is before publishing it again.
5. **A3** — either release, or stop advertising an install.
6. **B8, C12** — source real fixtures; round-trip one exported graph. These are
   the two places where the project's central claim ("quality-proven") is
   currently taken on trust.
