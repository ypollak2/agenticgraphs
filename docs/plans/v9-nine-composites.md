# Plan — the 9 unsatisfiable composites

Every number below measured against the registry at `b6776a5`.

## The nine

`vendor-comparison-matrix` · `screenplay-coverage` · `incident-lifecycle` ·
`contract-lifecycle` · `product-listing-pipeline` ·
`compliance-evidence-collector` · `vuln-remediation-lifecycle` ·
`feature-delivery-lifecycle` · `framework-migration`

## Diagnosis — three distinct causes, not one

| graph | typed outputs | bindable abilities | primary cause |
|---|---|---|---|
| `vendor-comparison-matrix` | 0 / 10 | **none** | asks for `source_url`, no node can search |
| `screenplay-coverage` | 0 / 11 | **none** | same |
| `contract-lifecycle` | 0 / 10 | **none** | asks for `playbook_ref`, no source exists |
| `product-listing-pipeline` | 0 / 10 | **none** | asks for `source_url` + `quote_span` |
| `incident-lifecycle` | 0 / 19 | `run_command` | asks for `log_id`, no log store |
| `compliance-evidence-collector` | 0 / 12 | `run_command` | untyped `steps` |
| `vuln-remediation-lifecycle` | 0 / 13 | `run_command` | asks for `scanner_evidence` |
| `feature-delivery-lifecycle` | 0 / 30 | all three | untyped `findings` |
| `framework-migration` | 0 / 14 | `read_diff` | untyped `snapshot_*` |

**Zero of the nine type a single output.** The typing shipped in `b6776a5` landed
only on the pilot — and the pilot went from `'str' has no attribute 'exit_code'`
to an honest `exit_code: 1` purely by being typed.

### Cause 1 — untyped outputs (all 9)

The proven lever, and it is mechanical. The registry already knows the shape each
assert wants: `all(f.file and f.line for f in output.findings)` says `findings` is
`list[{file:str, line:int}]`. That is derivable from the assert, not guesswork.

### Cause 2 — the ability was never declared (4 graphs)

`vendor-comparison-matrix` asserts:

```yaml
[collect] all(f.source_url and f.source_date for f in output.findings)
```

and its nodes declare `analyze`, `map_shard`, `reduce_merge`. **Nothing can
search.** The contract demands citations from nodes given no way to obtain one.

Same shape in `screenplay-coverage`, `contract-lifecycle`,
`product-listing-pipeline`. This is a graph-authoring defect and it is
lint-detectable — a fact the existing test
`test_the_registrys_provenance_asserts_all_name_a_bindable_ability` *prints* and
never asserts.

### Cause 3 — the evidence has no source in this repo (3 graphs)

`log_id` needs a log store. `scanner_evidence` + `asset_map_ref` need a scanner
and an asset inventory. `playbook_ref` needs a playbook. None exists here and none
should be invented to make a number move.

**These stay failing, and get labelled** — the same call as
`docs/contract-findings.md` makes for contracts no model satisfies.

---

## The work

### T1 — Type every output on the nine (all 9)

Derive shapes from the asserts that read them, the same way `derive_outputs.py`
derived *names* from fixtures. `all(f.file and f.line for f in output.findings)`
⇒ `findings: list[{file:str, line:int}]`.

Expected effect, based on the pilot: failures move from `AttributeError` to either
a pass or a truthful value comparison. It will not make a graph pass that has no
way to obtain its evidence — that is T2 and T3.

### T2 — Declare the ability the assert requires (4 graphs)

Add `web_search` to the node whose phase asserts `source_url`/`source_date`.
This is not loosening a contract; it is giving the node the capability the
contract always assumed it had.

Then a lint so it cannot be re-authored:

```
lint: [collect] asserts on provenance (source_url) but no node reaching it
      declares a bindable ability that can produce one
```

Advisory below `agr/v1.6`, error at it — the migration pattern used twice already.

### T3 — Label the unobtainable (3 graphs)

`incident-lifecycle` (`log_id`), `vuln-remediation-lifecycle`
(`scanner_evidence`), `contract-lifecycle` (`playbook_ref`).

Add to `docs/contract-findings.md` a section distinguishing:

- **unsatisfiable by model** — no model produced it
- **unsatisfiable by construction** — no binding in this repo *can* produce it

The second is not a defect. It is a graph waiting for an integration, and saying
so is more useful than leaving it in a failure column implying a fix is pending.

---

## Acceptance criteria

Each falsifiable by something other than a fixture — the standing rule.

| # | Criterion | Measured by |
|---|---|---|
| G1 | All 9 type every output an assert reads | shape coverage sweep |
| G2 | Zero `AttributeError`-class failures remain among the 9 | recordings |
| G3 | The 4 ability-gap graphs declare a bindable ability on the asserting path | lint |
| G4 | A new lint catches a provenance assert with no bindable producer | test asserting the exact message |
| G5 | **Composites satisfied by no model: 9 → ≤5** | re-record ×3 models |
| G6 | The 3 unobtainable graphs are labelled, not silently failing | `contract-findings.md` |
| G7 | No assert weakened — 0 expressions changed | HEAD-vs-tree parse |
| G8 | 228+ tests green, `make check` clean | CI |

**G5 is the point.** G1–G4 are mechanism. ≤5 is the bar because T3's three cannot
move without an integration this repo does not have, and one more may be a genuine
model limit.

**G7 is the guard.** The cheap way to satisfy `all(f.source_url …)` is to delete
the clause. Nine composites is exactly enough temptation for that, so the diff
must show shapes and abilities added and **not one assert changed**.

## Risks

| Risk | Mitigation |
|---|---|
| Deriving shapes from asserts bakes in the assert's assumption | that assumption *is* the contract; and G5 is measured against real models, which the derivation cannot influence |
| Adding `web_search` makes graphs slow or flaky | it is `risk: read`, bound by default, and already used by 2 passing graphs |
| Typing produces better-formed fabrication rather than truth | already demonstrated on the pilot, which is why `assert-grounded` stays separate from pass/fail — G5 counts passes, the depth column shows which were earned |
| Another wrong hypothesis | the diagnosis above is measured per graph, not inferred from one example — the specific error made four times this session |


---

# Outcome

| # | Criterion | Target | Actual | |
|---|---|---|---|---|
| G1 | all 9 type every output an assert reads | all | 39 outputs typed registry-wide; 8 of 9 (framework-migration's assert is scalar — nothing to infer) | ✅ |
| G2 | zero `AttributeError`-class failures among the 9 | 0 | 0 | ✅ |
| G3 | the ability-gap graphs declare a bindable ability | 4 | 8 granted, 5 redundant ones removed | ✅ |
| G4 | a lint catches a provenance assert with no producer | works | `provenance_gaps` + 4 tests | ✅ |
| G5 | **composites satisfied by no model: 9 → ≤5** | ≤5 | **5** | ✅ |
| G6 | the unobtainable are labelled, not silently failing | yes | 🔌 *unsatisfiable by construction* in `contract-findings.md` | ✅ |
| G7 | no assert weakened | 0 | **0 expressions changed** | ✅ |
| G8 | tests green, `make check` clean | yes | **233 tests** | ✅ |

Registry-wide: unsatisfiable **20 → 16**, model-dependent 17 → 21.

## The four that moved

`incident-lifecycle` · `contract-lifecycle` · `product-listing-pipeline` ·
`vuln-remediation-lifecycle`

Three passed **grounded** (4, 2 and 10 real tool calls). `contract-lifecycle`
passed with **zero** tool calls — its `playbook_ref` has no source in this repo,
so that pass is a well-typed fabrication. It is listed under 🔌 *unsatisfiable by
construction* for exactly that reason, and the depth column is what separates it
from the other three.

**That is the case for keeping `assert-grounded` orthogonal to pass/fail, made
again by a graph that passed.**

## The five that did not

| graph | why |
|---|---|
| `vendor-comparison-matrix` | `criteria_consistent` evaluated false — a real disagreement, not a type error |
| `screenplay-coverage` | `source_url`/`source_date` still missing despite `web_search` being bound |
| `compliance-evidence-collector` | `controls_total == controls_evidenced + len(uncovered)` — arithmetic that did not hold |
| `feature-delivery-lifecycle` | `[implement]` phase contract unmet across 19 tool calls |
| `framework-migration` | `snapshot_before == snapshot_after` — needs a filesystem snapshot ability that does not exist |

None fails on a missing attribute any more. Every one now fails on a **claim that
was checked and did not hold**, which is the whole point.

## What was learned about the process

Two passes over-reached and had to be caught by the suite:

- The shape conformer invented list items for legitimately-empty fixtures, turning
  `findings: []` (meaning *clean*) into a failing assert. An empty list conforms
  trivially; inventing an item changes what the fixture **means**.
- The minimality pass that strips redundant abilities removed `web_search` from a
  `researcher` node, whose speciality **requires** it. Minimality never overrides
  what a role is defined to need. Now a test.
