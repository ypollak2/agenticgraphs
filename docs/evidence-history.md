# What real models actually did — the record

This is the version-by-version account of what live recording found, moved out of
the README in v1.8. It is kept because the findings are the most useful thing this
project produced, and cut from the README because three different snapshots of the
same number were sitting in one document with nothing saying which was current.

> **Every number below is superseded.** All 560 recordings predate agr/v1.8, which
> stopped the runner passing each node the asserts it was about to be scored on,
> pinned sampling, and replaced sixteen self-graded contracts. None of it is
> comparable to a v1.8 run — see [agr-v1.8.md](agr-v1.8.md) and
> [live-coverage.md](live-coverage.md). Read this as the history of how the
> evaluation was found to be wrong, not as evidence about the graphs.

What real models actually did

The most useful thing this project produced is a failure. `assert-live` grading
shipped in v1.1 but nothing could produce it, so every graph sat at `assert-fixture`.
v1.2 made recordings possible and pointed a local `qwen2.5-coder:7b` at five graphs.

**All five failed.** Every one raised `NameError: name 'output' is not defined` — on
the exact key its contract asserts. The cause was not the model. `LLMRunner`'s prompt
had said *"reply with a JSON object of your output keys"* since v1.0 and never said
**which**; v1.1 added declared `outputs` contracts and the live runner never read
them. Worse, declared outputs existed only on composites — all 74 primitives had no
contract for a model to aim at.

After teaching the runner to state the contract, **4 of 5 pass**. The fifth is kept,
failing, because the model returned `output: true` where an object is required.

A registry reporting 74/74 at 100% was, on first contact with a real model, 0/5.

v1.3 then recorded **75 runs — 25 graphs × 3 models** — and the same lesson landed
twice more. v1.5 re-recorded the identical sweep after giving every dependent node
a declared output:

| Model | v1.3 pass | **v1.5 pass** | unparseable |
|---|---|---|---|
| `qwen3-coder:30b` | 19/25 | **24/25** | 0 |
| `hermes3:8b` | 7/25 | **14/25** | 8 → 5 |
| `qwen2.5-coder:7b` | 11/25 | 11/25 | 3 → 2 |

Contracts satisfied by **no** model: 4 → 1 → 0 **across the 25 graphs then recorded.**

## That number was read off a slice, and the slice was the smallest 25 graphs

Recording **all 83** — every composite and every human-gated graph, for the first
time — gives a different picture:

| | 25-graph slice | **all 83** |
|---|---|---|
| satisfied on every model | 13 | **42** of 83 |
| satisfied by **no** model | 0 | **27** of 83 |

And it is not spread evenly:

| shape | satisfied by no model |
|---|---|
| primitive | 11 of 65 |
| human-gated | 2 of 4 |
| **composite** | **14 of 14** |

**Every multi-phase composite failed on every model** — the graphs that were the
whole thesis of v1.1. The sample said 96%; the registry was 64% on its strongest
tested model, and 0% on its most ambitious graphs.

Reading those recordings found two structural bugs, not a prompt problem: a phase
merge that lost any fact a later node overwrote, and asserts reading
`output.violations` while nodes declared `outputs: [violations]` — two conventions
for one contract, with the declaration being the one the model was told. Fixing
both moved the registry to **48 clean / 21 unsatisfied**, and 3 composites now pass.

The remaining composite failures are no longer misplaced facts: the required key is
absent from the blackboard entirely. That looked like a model-scale limit, so it
was tested against `gpt-4o`:

| model | composites passing |
|---|---|
| `qwen3-coder:30b` (local) | 3 of 14 |
| `gpt-4o` (frontier) | **4 of 14** |

**One graph better — and `procurement-lifecycle` passes on the 30B model and fails
on `gpt-4o`.** Not a capability ladder. The hypothesis was wrong.

Classifying all 28 remaining failures: **18 demand a grounded provenance field** —
`source_url`, `log_id`, `file`+`line`, `exit_code`, `scanner_evidence`,
`snapshot_before`. Facts no model can obtain by generating. **A model that passed
them would be fabricating provenance.**

Which means the contracts are working. Every graph declares abilities —
`web_search`, `sast_scan`, `run_command` — and `agr adapt` has always emitted
`NotImplementedError: bind speciality X`. **No run in this repo has ever bound a
tool.** `LLMRunner` sends a prompt and parses JSON; that is all it does.

The graphs whose contracts are satisfiable by generation alone pass at 47 of 83.
The ones that demand evidence correctly refuse. See
[`docs/plans/v8-frontier-finding.md`](docs/plans/v8-frontier-finding.md).

## So the abilities got bound — and the pilot graph stopped passing

`docs-code-sync-audit` asserts `all(e.exit_code == 0 for e in output.examples)`.
Run against `gpt-4o` twice:

| | tool calls | result | depth |
|---|---|---|---|
| tools **off** | 0 | **PASS** | `assert-live` |
| tools **on** | 20, all succeeded | **FAIL** | `assert-grounded` |

**It only ever passed because the model fabricated `exit_code: 0`.** With
`run_command` actually bound it fails, and the failure is the correct answer.

A new depth grade sits above `assert-live`:

```
describe-only < assert-fixture < assert-live < assert-grounded < command
```

`assert-grounded` means the assert held *and* the values trace to a recorded tool
call. It does **not** mean the call was the right one — on that pilot run several
of the 20 were theatre (`echo 'Running test command 2'`). The trace proves
something ran, not that the right thing ran. Stated plainly, because
`assert-fixture` went over-read for five versions.

Typing every output the asserts read (116 of them) then moved 3 more graphs — and
**only 1 of the 3 was grounded.** The other two pass by producing a well-typed
value for a fact nothing in this repo can establish, and both are labelled 🔌
*unsatisfiable by construction*.

**Typing is necessary and not sufficient.** A type tells a model what a key should
be; it does not make the model obtain it. See
[`docs/agr-bindings.md`](docs/agr-bindings.md) and
[`docs/plans/v10-remaining-sixteen.md`](docs/plans/v10-remaining-sixteen.md).

This is exactly the failure [`docs/live-coverage.md`](docs/live-coverage.md) exists
to prevent, made one commit before that report was written. A pass rate over the
easiest quarter of a registry is not a pass rate.

Four versions in, the pattern has a name: **anything optional in the spec ends up
unused, and anything unused ends up load-bearing by accident.** `outputs` was
optional from v1.1; 29% of nodes skipped it and the whole registry depended on them
anyway. Each version's headline failure was the same shape — the artifact looked
complete and the runtime had nothing to work with.

A large share of apparent *model* failure was the harness again: `LLMRunner`
extracted JSON with `text[text.index("{"):text.rindex("}")+1]`, which breaks on
markdown fences, trailing commas and Python `True`/`False`. Hardening it moved
qwen2.5-coder from 8 passes to 11.

And model choice dominates. On v1.2's single-model evidence, **12 graphs looked like
bad contracts that a larger model satisfies perfectly.** Only disagreement between
models separates "this contract is unsatisfiable" from "that model was weak" —
which is why the scoreboard reports per-model results and
[`docs/contract-findings.md`](docs/contract-findings.md) names the contracts no
model satisfies.

