# Autonomy: unattended writes to the registry

This document covers the full detail behind the "Unattended operation" section of the
README's [For Agents](../README.md#-for-agents) section: how to run agenticgraphs with no
human in the loop, and exactly what safety net stays in place when you do.

## Philosophy: safe by default, opt-in for real

Every mutation path in this repo — `agr infuse`, `agr optimize --apply`, and the MCP
`infuse_ability` tool — is, by default, a **human-owned-checkout** operation. Nothing
writes to `graphs/` unless a human is either running the command themselves or has
explicitly flipped an opt-in switch for a specific unattended run. There is no global
"trust this agent forever" setting; the switch is an environment variable (or a per-call
flag) that only affects the process it's set in.

## The gate, unchanged

Autonomous persistence does **not** bypass any of the checks a human-driven `agr infuse`
would go through. Every autonomous write still passes:

1. **Schema validation** (`validate_schema` against `spec/agr-graph.schema.json`)
2. **MAST lint** (`lint_graph` — duplicate/dangling/unreachable nodes, missing
   verification blocks, unbounded back-edges, unresolved specialities/abilities)
3. **Lineage logging** (`lineage.yaml` sidecar next to the graph, same as any other
   mutation)

If the gate rejects the mutation, nothing is written — autonomous or not, exactly as
today.

## Turning it on

Two independent env vars, both required for different things:

| Variable | Effect |
|---|---|
| `AGR_AUTONOMOUS=1` | Required for any unattended persist. Without it, `infuse_ability(persist=true)` and `agr optimize --apply` (outside a TTY, or without `--autonomous`) refuse with a clear error. |
| `AGR_AUTONOMOUS_ALLOW_EXECUTE=1` | Additionally required to autonomously persist an ability whose `risk` is `execute` (see [Execute-risk cap](#execute-risk-cap-on-autonomous-persist) below). |

A CLI-level `--autonomous` flag on `agr optimize` is equivalent to setting
`AGR_AUTONOMOUS=1` for that invocation.

### MCP: `infuse_ability(persist=true)`

`agr mcp` (stdio or `--http`) exposes `infuse_ability(name, node_id, ability, persist=False)`.
By default (`persist=False`, unchanged from before this feature) it returns a validated
mutated *copy* of the graph YAML — nothing is written.

With `persist=true`:

```
AGR_MCP_TOKEN=$(openssl rand -hex 32) AGR_AUTONOMOUS=1 agr mcp --http --port 8765
```

Over HTTP the token is mandatory once `AGR_AUTONOMOUS=1` is set: `agr mcp --http`
refuses to start without it. Loopback-only binding stops remote callers, not the
other processes on the same machine, and an unattended server that can commit is
exactly the one that must know who is calling. Clients send
`Authorization: Bearer <token>`; anything else gets `401`. Over stdio the parent
process *is* the caller, so no token applies.

...and then a call to `infuse_ability(name="code-review-pipeline", node_id="triage",
ability="edit_files", persist=true)` will, if the gate passes:

1. Write the mutated `graph.yaml` to disk.
2. Append a `lineage.yaml` entry (as any `infuse` does), tagged `"autonomous": true`.
3. Commit both files onto a dedicated `auto/mutations` branch (see below) — **never**
   `main`, and the commit is **never pushed** anywhere.

If `AGR_AUTONOMOUS` is not set, the call raises immediately with:

```
autonomous persist refused: AGR_AUTONOMOUS is not set. Writing to the registry is a
human-owned-checkout operation by default — set AGR_AUTONOMOUS=1 (or pass --autonomous /
persist through an autonomous run) to opt this run into unattended writes.
```

### CLI: `agr optimize --apply`

Without `--autonomous` (and without `AGR_AUTONOMOUS=1` in the environment):

- If stdin is a TTY, `--apply` prompts for confirmation (`apply optimizer changes to
  '<name>'? [y/N]`) before writing.
- If stdin is **not** a TTY (i.e. this is already an unattended context — cron, CI, a
  headless recipe), `--apply` refuses outright rather than silently blocking on a prompt
  no one will answer.

With `--autonomous` or `AGR_AUTONOMOUS=1`, `--apply` runs straight through, no prompt.

`agr optimize --apply --autonomous` goes through `commit_autonomous_mutation` exactly
like an MCP persist: the change lands on `auto/mutations`, never on the checked-out
branch, and is never pushed. (Until the 2026-09-04 audit the optimizer wrote straight
into the live checkout under the same flag — one switch, two blast radii.)

## Execute-risk cap on autonomous persist

Abilities declare a `risk` field in their YAML (`spec/agr-ability.schema.json`): `read`,
`write`, or `execute`. `execute`-risk abilities (e.g. `abilities/run_command.yaml`) are
capped even when `AGR_AUTONOMOUS=1` is set: persisting a graph mutation that adds an
`execute`-risk ability additionally requires `AGR_AUTONOMOUS_ALLOW_EXECUTE=1`. This is a
deliberate second gate — general "let this run write things back to git" trust does not
imply "let this run wire up a node that can execute arbitrary commands." Refusal message:

```
autonomous persist refused: ability risk surface is 'execute'. Execute-risk abilities are
capped even under AGR_AUTONOMOUS — set AGR_AUTONOMOUS_ALLOW_EXECUTE=1 to explicitly allow it.
```

## The `auto/mutations` branch

Autonomous MCP persists (`infuse_ability(..., persist=true)`) never touch `main` and never
touch the currently checked-out branch or the human's staged index. Implementation
(`agenticgraphs.autonomy.commit_autonomous_mutation`):

1. Build a scratch git index (`GIT_INDEX_FILE` pointed at a throwaway file under `.git/`).
2. Seed it from the tip of `refs/heads/auto/mutations` if that branch already exists,
   else from `HEAD` — so the branch is either extended or forked fresh from wherever the
   checkout currently is.
3. Stage exactly the mutated `graph.yaml` and `lineage.yaml` into that scratch index.
4. `write-tree` + `commit-tree` against that parent, with the commit message
   `auto: <graph> <ability> <node> [autonomous]`.
5. Move `refs/heads/auto/mutations` (only that ref) to the new commit.

Author/committer identity is read from the repo's own `git config user.name` /
`user.email` (falling back to a generic `agenticgraphs-autonomy` identity if unset) — the
same identity a human commit in that checkout would use.

**Nothing is ever pushed.** Inspect what an autonomous run has committed with:

```
git log auto/mutations
git diff main..auto/mutations
```

...and merge/cherry-pick/rebase it into `main` yourself when you're satisfied — the
autonomy gate produces a reviewable branch, not a fait accompli on `main`.

## Related

- [`scripts/install_service.sh`](../scripts/install_service.sh) — always-on `agr mcp --http`
  as a macOS LaunchAgent (separate from, and not gated by, autonomy — it just serves the
  read-only tools plus `persist=false` infusion unless you *also* export `AGR_AUTONOMOUS=1`
  **and** `AGR_MCP_TOKEN` in the LaunchAgent's environment — the server will not start
  autonomous over HTTP without a token).
- [`scripts/headless_run.sh`](../scripts/headless_run.sh) — a non-interactive `claude -p`
  recipe scoped to `Bash(uv run agr *)`, deliberately not touching the autonomy gate at
  all (it only searches/evals, never infuses or optimizes).
- [`src/agenticgraphs/autonomy.py`](../src/agenticgraphs/autonomy.py) — the gate
  implementation.
