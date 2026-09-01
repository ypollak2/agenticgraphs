# Eleven graphs cannot express their own failure

Found by reading the first complete v1.8 recording sweep, not by reading the spec.

## What the sweep reported, and what it meant

27 of 83 graphs failed. Nine of them reported `AttributeError: <key>` — which reads
as a model that could not format its output. It was not. The producing node had
never executed:

| graph | missing key | produced by | did it run |
|---|---|---|---|
| `hiring-lifecycle` | `scorecard_count` | `offer` | no |
| `invoice-reconciliation` | `unreviewed_exceptions` | `post` | no |
| `trial-eligibility-screener` | `unreviewed_ambiguous` | `enrol` | no |
| `regulatory-filing-lifecycle` | `signed_off` | `controller-signoff` | no |
| `incident-lifecycle` | `actions` | `action-items` | no |
| `vuln-remediation-lifecycle` | `advisory_url` | `disclose` | no |
| `performance-cycle-summarizer` | `uncited_claims` | `calibrate` | no |
| `feature-delivery-lifecycle` | `doc_changes` | `docs` | no |

`unreached_terminals` now names this directly. It existed on `RunReport` before
this analysis and was never written into the profile, so the better diagnosis was
computed and thrown away — the reports still said `AttributeError`.

## The structural cause

24 nodes across 21 graphs have forward edges that are *all* conditional. They split
in two, and only one half is a defect.

**Exhaustive pairs — 13 nodes.** `complexity <= moderate` beside
`complexity > moderate`, or `len(x) == 0` beside `len(x) > 0`. Every value is
covered, so the run strands only when the model omits the key entirely. That is
arguably correct behaviour: a router cannot route without a classification, and
inventing a default would route on a guess.

**A lone happy path — 11 nodes.** `prove -> disclose-approval when exploit_blocked`.
`reconcile -> controller-signoff when reconciled`. `integrate -> sign-off when
suite_green`. `rights-check -> publish when rights_clear`.

When the condition is false there is no edge at all. Not to a compensator, not to
an escalation, not to a terminal that records the failure. **The graph has no way
to say "it did not work."** It does not fail — it stops, and the contract then
reports a missing key from a node that was never reached.

This is the same shape as the dead-guard finding: behaviour the registry advertised
(bounded retry, escalation, compensation) that the topology could not actually
perform. There, the guard could never be true. Here, there is nothing on the other
side of it.

## What a fix looks like

Every conditionally-guarded fork needs one of:

- an **exhaustive complement** — the negation, routing to an escalation or a
  terminal that records the outcome;
- an **existing failure path** — a compensate or error edge already covers it;
- an explicit **`on_timeout: escalate`**, which the approval nodes already use.

`regulatory-filing-lifecycle` is the clearest case. Its live run reconciles three
times, fails each time, exhausts `attempts < 3`, and then has nowhere to go — the
filing is neither made nor formally abandoned. A finance graph that cannot record
"we could not reconcile" is missing the outcome that matters most.

## Status

Not yet fixed. The recording sweep reloads every `graph.yaml` at record time, so
editing the corpus mid-sweep produces a baseline whose halves measure different
graphs. Queued behind the n=3 run.
