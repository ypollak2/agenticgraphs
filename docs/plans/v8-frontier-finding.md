# The frontier run — what the composites actually need

Not a version. One experiment, and the result changes what the remaining work is.

## The question

v1.7 closed the last structural gap and left 11 composites failing. The audit's
stated hypothesis:

> *"these composites are not achievable with 7B–30B local models. The next useful
> measurement is a frontier model, not another harness patch."*

## The answer: no

All 14 composites, `gpt-4o` via the OpenAI API:

| model | composites passing |
|---|---|
| `qwen3-coder:30b` (local) | 3 of 14 |
| **`gpt-4o` (frontier)** | **4 of 14** |

One graph better. And not cleanly better — `procurement-lifecycle` passes on the
30B model and **fails** on `gpt-4o`. That is not a capability ladder; it is noise
around a floor.

**The hypothesis was wrong.** Model scale is not what these composites are short of.

## What they are actually short of

Classifying all 28 remaining composite assert failures:

| what the assert demands | count |
|---|---|
| **a grounded provenance field** | **18** |
| anything else | 10 |

The provenance failures, in full:

```
[collect]      all(f.source_url and f.source_date for f in output.findings)
[postmortem]   all(e.get('log_id') or e.get('message_id') for e in output.timeline)
[redline]      all(r.playbook_ref for r in output.redlines)
[claim-check]  all(v.source_url and v.quote_span for v in output.verdicts)
[collect]      all(s.exit_code == 0 for s in output.steps)
[prioritize]   all(r.scanner_evidence and r.asset_map_ref for r in output.ranking)
[audit]        all(f.file and f.line for f in output.findings)
[port-slice]   output.snapshot_before == output.snapshot_after
```

Every one requires a fact the model **cannot obtain by generating**: a URL that
resolves, a log line that exists, a command's exit code, a file and line number, a
scanner's output, a filesystem snapshot.

**A model that passed these would be fabricating provenance.** The contracts are
doing exactly what they were written to do — refusing an answer that has no
evidence behind it — and the runner has no way to supply that evidence.

## This is a validation of the contract design, not a failure of it

The registry's abilities have always said this out loud:

```yaml
abilities: [web_search, sast_scan, run_command, read_diff]
```

`agr adapt` emits `NotImplementedError` for each, with the message *"bind
speciality X (abilities: …)"*. Structure is compiled; behaviour is bound. **The
abilities were never bound in any run in this session** — `LLMRunner` sends a
prompt and parses JSON, and that is all it has ever done.

So the composites are not failing. They are correctly reporting that nobody wired
up their tools.

The graphs whose contracts *are* satisfiable by generation alone — summarise,
classify, draft, adjudicate — pass at 47 of 83. The ones that demand evidence do
not, and should not, until an ability binding exists.

## What the next version is, and is not

**Not** another harness patch, and **not** a bigger model.

The honest next step is an **ability-bound runner**: `web_search` reaching a real
search API, `run_command` executing in a sandbox, `read_diff` reading an actual
diff. That is the difference between a registry that describes agentic workflows
and one that runs them.

Until then the README should say — and now does — that 19 of 83 graphs carry
contracts requiring tool-grounded evidence, and that no run in this repo has ever
bound a tool.
