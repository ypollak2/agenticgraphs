# Ability bindings — grounding a claim

## Why

18 of 28 remaining composite assert failures demanded a **grounded provenance
field**: a URL that resolves, a command's exit code, a file and line number. No
model can produce those honestly, and one that appears to is fabricating them.

Every run in this repo's history sent a prompt and parsed JSON. The seam for
binding real implementations shipped in M0 —
`spec/agr-ability.schema.json` has carried `binding: {kind, ref}` since the first
commit — and **0 of 32 abilities ever declared one.** This fills that seam rather
than inventing a parallel mechanism.

## The demonstration

`docs-code-sync-audit` asserts `all(e.exit_code == 0 for e in output.examples)`.
Run against `gpt-4o` twice:

| | tool calls | result | depth |
|---|---|---|---|
| tools **off** | 0 | **PASS** | `assert-live` |
| tools **on** | 20, all succeeded | **FAIL** | `assert-grounded` |

**It only ever passed because the model fabricated `exit_code: 0`.** With
`run_command` actually bound it fails, honestly, and the failure is the correct
answer.

That is the whole case for the binding layer in one graph.

## What `assert-grounded` does and does not mean

The depth ladder, weakest first:

```
describe-only < assert-fixture < assert-live < assert-grounded < command
```

`assert-grounded` means the assert held **and** values behind it trace to a
recorded tool call.

**It does not mean the tool call was the right one.** On the pilot run `gpt-4o`
made 20 real calls, several of them theatre — `echo 'Running test command 2'` —
and then described the results in prose instead of returning structured records.
The trace proves *something ran*, not that the *right* thing ran.

Still strictly stronger than `assert-live`, where nothing ran at all. Stated here
so the grade is not over-read, which is how `assert-fixture` was over-read for
five versions.

## Design

**Bounded, never a toolbox.** Only the abilities a node declares are resolved and
offered. The registry's premise is that what a node may do is written down; an
open tool set discards exactly that.

**Risk is the permission model, and it already existed.** `abilities/*.yaml` has
declared `risk: read|write|execute` since M0 — 18 read, 6 write, 8 execute.
`read` binds freely; `write`/`execute` need `AGR_ALLOW_MUTATING=1`, the same gate
`agr eval --run-commands` uses.

**Failed calls are recorded too.** A trace that only contains successes is not a
trace, and `rep.grounded` requires at least one *successful* call rather than any
call at all.

**The trace survives recording.** Grounding is a property of the run, not of the
node outputs, so recordings carry `tool_calls`. Without that, replaying a grounded
run graded `assert-live` and the strongest evidence in the repo could never reach
CI — the identical failure `assert-live` itself had before recordings existed.

## Bound today

| ability | risk | unlocks |
|---|---|---|
| `run_command` | execute | `exit_code`, `snapshot_before/after` |
| `read_diff` | read | `file` + `line` |
| `web_search` | read | `source_url`, `source_date` |

`log_id`, `scanner_evidence`, `playbook_ref` need systems this repo has no
binding for. Those contracts stay unsatisfiable, and that is the truthful state —
not a defect to paper over.

## Usage

```bash
AGR_TOOLS=1 AGR_ALLOW_MUTATING=1 \
AGR_LLM_BASE_URL=... AGR_LLM_MODEL=gpt-4o \
  uv run python scripts/record_live.py docs-code-sync-audit
```

Omit `AGR_ALLOW_MUTATING` to bind only read-risk abilities.
