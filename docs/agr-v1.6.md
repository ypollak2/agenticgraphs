> **Superseded by [AGR v1.8](agr-v1.8.md).** This page describes an earlier version and is kept for the record; the current spec is agr-v1.8.md.

# AGR v1.6 — provenance

One lint, armed per graph. The registry skipped this number: no shipped graph
declares `apiVersion: agr/v1.6`, and `docs/agr-v1.7.md` explains why.

This document was written after the fact (2026-09-04 audit, D1-03): the version
existed as an enum value and a lint arm-condition with no spec page. Facts from
`validate.py` (`provenance_gaps`, `_lint_provenance`, `PROVENANCE_FIELDS`,
`GROUND_TRUTH_FIELDS`), `bindings.py` and `CHANGELOG.md` §0.8.0.

## The gap this closes

`vendor-comparison-matrix` asserts
`all(f.source_url and f.source_date for f in output.findings)` while its nodes
declare `analyze`, `map_shard`, `reduce_merge`. Nothing can search. The contract
demands citations from nodes given no way to obtain one — a graph-authoring
defect, not a model failure — and it went undetected for nine versions because
nothing ever asked.

## What v1.6 adds

### `provenance_gaps(doc)`

For every `verification[].assert`, the set of attribute names it touches is
intersected with `PROVENANCE_FIELDS` (`source_url`, `source_date`, `log_id`,
`message_id`, `exit_code`, `file`, `line`, `quote_span`, `playbook_ref`,
`scanner_evidence`, `asset_map_ref`, `advisory_url`, `pr_url`, `spdx`, `citation`).
If the assert wants any of those and **no node on the graph declares an ability
with a real binding** (`bindings.BUILTINS`), the assert is a provenance gap.

A second set, `GROUND_TRUTH_FIELDS`, names facts no binding can obtain regardless
— an on-call ownership map, a policy table. Those asserts are reported as
*unsatisfiable by construction* rather than as a model failure, which is the
distinction `docs/contract-findings.md` draws between 🚫 and 🔌.

### `_lint_provenance` — armed at `agr/v1.6` only

```python
if doc.get("apiVersion") == "agr/v1.6":
    return [f"lint: {m}" for m in msgs]
return []
```

At exactly v1.6 a provenance gap is a lint **error**. At every other version the
gap is computed and surfaced through `contract-findings.md`, not enforced. The
per-graph arm was the design: migrating all 83 graphs through the hard lint at once
would have failed `clinical-protocol-lifecycle` on a ground-truth field no binding
here can obtain and armed an unrelated escalation. v1.7 kept the lint and moved the
registry past the number.

### Why it is a version and not a flag

The `apiVersion` enum is the only per-graph switch the linter reads. Arming a rule
on a version means a contributor opts in by stating the version their graph is
written against, and the registry can carry graphs at different strictness without
a second configuration surface.

## What v1.6 does not claim

That a bound ability was *called*, or that its result was *relevant* to the assert.
Grounding is proved at run time by `RunReport.grounded` (a successful `ToolCall`
exists) and graded as `assert-grounded` in the depth ladder; this lint only asks
whether obtaining provenance is *possible*. The remediation plan's R3-06 extends
the same idea to self-graded contracts: an assert whose every input is produced by
the verifier itself.

## Migration

None. Set `apiVersion: agr/v1.6` on a graph to arm the lint for it; the shipped
registry is at v1.8, where the gap is reported, not enforced.
