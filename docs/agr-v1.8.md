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

#### The provenance rule (2026-09-04 audit, D6-01)

The bare-truthy rule above was evaded by rewording: `output.matches_policy`
became `output.assigned_disposition == output.expected_disposition`, and the
verifier still declared both keys with no input from the policy table. So the
lint now asks about **provenance**, not syntax. In a comparison between two
blackboard values, if one side is produced *only* by a model-driven node with no
external anchor, and the other side passes through that same node, the node is
grading itself. A node is anchored when it declares `inputs` the caller supplies
(`state.inputs`), holds an ability with a real binding, or is `kind: human`.
Comparisons against literals are weak, and graded as such, but not circular.

The 16 graphs this recovered were fixed structurally: seven declare the caller's
reference table as the verifier's input; six moved a threshold the model used to
invent into `state.inputs` (the caller sets the bar); three moved the reference
side to the node that actually establishes it. At run time a node may no longer
overwrite a key the caller seeded: the caller's value is kept and the attempt is
recorded on `RunReport.overwritten_inputs`.

### Everything else that now has to be true

| Rule | Refuses |
|---|---|
| `_lint_self_graded` | a contract any model-driven node grades itself on |
| `_lint_criteria` | a verifier with no rubric |
| `_lint_commands` | prose in the `command` field |
| `_lint_irreversible` | a one-way effect with no compensating path |
| `_lint_motif` | a graph that declares a motif its topology does not have |
| `_lint_flow_keys` | an edge guard or approval contract on a key nothing produces |
| `_lint_runtime_keys` | a node declaring a key the runtime owns |
| `safeexpr` | any expression construct outside a small allowlist |

`_lint_motif` matters more than it looks. Ten graphs declared `parallel-swarm`
while being a linear three-node chain — including `verifier-swarm`, which the
README uses to explain what a swarm is. A motif nothing verifies is the same
defect as a contract nothing verifies.

### The rule the registry was missing: flags may route, they may not grade

Replacing the self-graded contracts deleted flags that were *also* routing guards
— `exploit_blocked`, `impact_cleared`, `suite_green`. Dropping them from the
CONTRACT was right. Dropping them from the node's OUTPUTS disabled each graph's
second half, and `regulatory-filing-lifecycle` could no longer reach its human
gate at all.

**A model-written flag may drive control flow; it just may not be the thing the
contract checks.** Routing on a model's judgement is what a router *is*. Grading a
model on its own judgement is what v1.8 refuses. The two had never been
distinguished, which is why the first fix broke the second property while fixing
the first.

`_lint_flow_keys` exists because that mistake was already latent, 52 times over.
`edge_true` catches every exception and returns `False`, so an edge guarded on a
key nothing produces is not an error — it is an edge that is never taken. Every
`verify_failed and attempts < 3` retry, every `<node>_failed` compensator, every
`revision_requested` review loop across 43 graphs was dead, and every golden case
passed anyway because a fixture supplies the key by hand. Only a live run reaches
the guard with a blackboard a model wrote.

v1.7 found exactly this for `attempts` and fixed that one name by publishing it
from the runtime. The hole stayed open for every other key. `unconnected_keys` has
applied the same rule to verification asserts since v1.4; control flow deserves it
more, because **a broken assert reports a failure and a broken guard reports
nothing at all.**

`_lint_runtime_keys` is the other half. A node that declares `attempts` lets a
fixture pin the counter, and the bounded loop it guards never terminates —
`verifier-swarm` ran to the step cap the moment the guard started working. Nothing
needs to declare it: `output.attempts` resolves through `OutputView`'s
fall-through to the blackboard.

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

### Runtime facts the linter used to imply and the runtime did not deliver

Closed by the 2026-09-04 gap audit (`docs/plans/audit-gaps-2026-09-04.md`), stated
here so the spec and the code say the same thing.

**`fan_out.on_partial: continue` means "aggregate over the shards that succeeded".**
A failed shard leaves `None` in the fanned-out list for every declared output, and
the node-level `error` flag is set only under `on_partial: fail`. `aggregate` with
`median` or `best` skips the `None`s; `union` and `majority` see them. Per-shard
errors are published as `shard_errors`, next to the runtime-owned `shards_processed`
and `shards_failed`, which a guard or assert may read without any node declaring them.

**`parallel_group` declares independence, not concurrency.** Members of a group may
run in any order or at the same time because nothing in the group depends on
another member. The reference runtime in `harness.py` schedules them serially, one
ready node per step. `_lint_motif` requires a two-member group or a `fan_out` for
`parallel-swarm` and `map-reduce` because the *shape* is what the motif claims;
a concurrent scheduler is a runtime property, tracked as remediation item R6-03.

**A `kind: verifier` node must be reachable on the flow path.** Reachability in
general counts `error` and `compensate` edges, because a rollback handler is a real
node. A verifier that only a failure edge reaches never runs on the path the
contract is about, so `lint_graph` refuses it.

**`agr validate` walks `ref` chains.** A cycle between composites, or nesting past
`MAX_DEPTH`, fails at validate time. Before, only `expand()` at run time saw it.

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

### The failure taxonomy, and `timeout_s`

A run used to fail in three ways the report could not name: a model reply with no
JSON object escaped as `ValueError`, a human gate nobody could sign escaped as
`HumanGateRequired`, and a node could run for close to an hour with nothing to
stop it. The recorder collapsed the first two into one string and wrote no
recording, so the cell vanished from every denominator (2026-09-04 audit, D3-03,
D3-02). `RunReport` now carries:

| field | set when | effect |
|---|---|---|
| `parse_failures` | a reply had no JSON object | node yields `error: parse`, so `retries` and error edges apply |
| `gate_refused` | a `kind: human` gate had no signer | the run stops; `passed` is False |
| `timeouts` | a node exceeded `timeout_s` (or the run-wide `node_timeout`) | node yields `error: timeout`; retries and error edges apply |

`failure_kinds` summarises them (`parse`, `gate`, `timeout`, `assert`, `command`,
`stall`, `budget`) and is written into every recording and profile, which is what
lets `contract-findings.md` count unparseable samples instead of dropping them.

`nodes[].timeout_s` is a per-node wall-clock deadline in seconds, enforced by the
reference runtime; unset means unbounded.

### Durability and the journal

`durability.checkpoint: every_node` (v1.3) makes a run journal one record per
executed node. `agr eval --journal DIR` writes `DIR/<case_id>.jsonl`;
`agr eval --resume-from FILE` reads it back, replays the recorded outputs, skips
the nodes they complete, and routes every resumed node through the same edge
resolution a fresh node takes.

The record shape, pinned by `tests/test_journal_shape.py`:

```json
{"node": "<node id>", "out": {<the node's output dict>}}
```

One JSON object per line, execution order, exactly these two keys. A future
version may **add** keys; it may not rename or drop `node` or `out`, because
resume keys completion on the first and replays the second. Frames a resumed run
replays are not re-journalled (`resumed: true` frames are excluded), so a journal
written after a resume is the union of both runs.

Before this section existed nothing produced the file `--resume-from` consumed
(2026-09-04 audit, D3-04).

### The HTTP transport

`agr mcp --http` binds `127.0.0.1` only, which does not distinguish the intended
caller from any other local process. With `AGR_MCP_TOKEN` set, every request must
carry `Authorization: Bearer <token>` or is answered `401` before the server sees
it. The token is **required** when `AGR_AUTONOMOUS=1`: an unattended server that can
commit to `auto/mutations` must not accept writes from whoever finds the port.

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
