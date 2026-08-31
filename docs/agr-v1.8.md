# AGR v1.8 — the claim

A graph now carries what it knows, and every claim it makes is checked by
something other than the model making it.

## The gap this closes

v1.7 gave a graph its subject. It still had nothing to say *about* that subject.

A node held its position in a topology — `speciality`, `abilities`, `outputs` —
and nothing else. So `clinical-literature-triage` and `incident-triage-router`
were the same four nodes differing in name, description and category: a
healthcare graph whose nodes were called `branch-simple` and `branch-complex` and
which contained no healthcare. Stripping the strings that are free to differ,
**36 of 83 graphs were byte-identical to another**, and 83 graphs were 40 shapes.

The domain knowledge is the rubric, and there was no field to hold it. A
downloaded graph was a shape you could have typed yourself.

Three claims were being made and none was checked:

| Claim | What checked it |
|---|---|
| this contract holds | the model, which wrote the flag the contract read |
| this graph is a `parallel-swarm` | nothing |
| this expression is safe to evaluate | nothing — it reached `eval()` |

## What v1.8 adds

### `criteria` — the rubric

```yaml
- id: verify
  speciality: critic
  kind: verifier
  criteria: >
    The team the incident was routed to owns the affected service in the current
    on-call map, and the severity reflects observed customer impact rather than
    the reporter's urgency.
```

Required on every `kind: verifier` node. The runner gives it to the node **in
place of the assert text it used to leak**, and that substitution is the point:

- an *assert* is the marking scheme. Telling a node
  `["output.matches_ownership_map"]` and then scoring it on
  `output.matches_ownership_map` measures whether a model can echo a flag it was
  just shown.
- *criteria* are what the claim means in this domain — the thing a verifier has
  to reason about, and the thing that makes two identically-shaped graphs into
  two different graphs.

Criteria are carried into every emitted LangGraph stub, CrewAI goal and AutoGen
system message, because the stub is where behavior actually gets bound. Leaving
the rubric in a YAML file the implementer is not reading is how the healthcare
graph ended up with no healthcare in it.

### The self-graded contract, refused

A contract whose assert is a bare truthy read of a key the graph's own verifier
declares as an output holds whenever the model claims it does. Sixteen contracts
across fifteen graphs were built that way. They are replaced by:

- **cross-node comparison** — the verifier emits a measurement, compared against
  a fact an upstream node produced or the caller supplied. `assigned_team ==
  expected_team` can still be satisfied by a model that makes both equal, but it
  must name a team twice, in the trace, against a reference it did not write.
- **an executable command** — where the subject is a repository, a dataset or a
  live system, the exit code is the fact. Commands went 1 → 20, and the one that
  existed was the string `"user-supplied verify command must exit 0"`.

### Everything else that now has to be true

| Rule | Refuses |
|---|---|
| `_lint_self_graded` | a contract the verifier grades itself on |
| `_lint_criteria` | a verifier with no rubric |
| `_lint_commands` | prose in the `command` field |
| `_lint_irreversible` | a one-way effect with no compensating path |
| `_lint_motif` | a graph that declares a motif its topology does not have |
| `safeexpr` | any expression construct outside a small allowlist |

`_lint_motif` matters more than it looks. Ten graphs declared `parallel-swarm`
while being a linear three-node chain — including `verifier-swarm`, which the
README uses to explain what a swarm is. A motif nothing verifies is the same
defect as a contract nothing verifies.

`_lint_irreversible` deliberately excludes `edit_files`: a working tree is
reversible by `git revert`, and marking it as a saga step would dress a
reversible action in the vocabulary reserved for one-way ones. Filing with a
regulator is not reversible. That distinction is the rule; the three compensators
it produced are just its output.

### `{placeholder}` in a verification command

```yaml
verification:
  - describe: the caller's own verification command exits 0
    command: "{verify_command}"
```

Filled from the blackboard. A missing placeholder **raises** rather than running
a half-substituted command: `pytest {suite}` with no `suite` would run the whole
suite and report a pass for a check that never happened.

## Security

`edges[].when` and `verification[].assert` reached `eval()` with
`{"__builtins__": {}}`, which is not a sandbox. Any downloaded graph could run
arbitrary code on `agr eval`, with no opt-in and no warning, and `agr adapt`
inlined the same hole into every generated module. See [SECURITY.md](../SECURITY.md).

Fixing it surfaced a bug that had been there the whole time: the namespace was
passed as *locals*, and a comprehension body sees globals and its own bindings
but never the enclosing locals — so every **nested** quantifier raised
`NameError: name 'all' is not defined`. Single-level asserts hid it, because
their outermost iterable is evaluated eagerly in the enclosing scope. No contract
in the registry could quantify two levels deep until now.

## Migration

```sh
uv run python scripts/derive_criteria.py        # criteria on every verifier
uv run python scripts/fix_self_graded.py        # replace self-graded contracts
uv run python scripts/add_verification_commands.py
uv run python scripts/deepen_graphs.py
uv run python scripts/invalidate_recordings.py  # retire the pre-v1.8 evidence
```

The last one is not optional. Every live recording predates the prompt change,
the sampling change and the sixteen replaced contracts, so none of it is
comparable to a v1.8 run. The files are kept and stamped rather than deleted —
the record of what was measured is the evidence that the correction was needed —
and every report excludes them. **Live coverage reads 0 of 83, and that means
pending re-recording, not never measured.**

Re-recording needs a real endpoint and real spend. It is the one part of this
migration a checkout cannot perform for itself.

## What v1.8 does not claim

- The registry is not proven against real models. It has no valid live evidence
  at all until someone re-records.
- `criteria` are prose. They are excluded from `gen_clone_report.py`'s
  distinctness metric on purpose: counting them would let a registry of identical
  graphs look distinct because each was given a different sentence.
- Median graph size is 4 nodes. These are motif demonstrations with real
  contracts, not production workflows.
