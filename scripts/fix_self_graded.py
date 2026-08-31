"""Replace every self-graded contract with a check the model cannot simply assert.

A self-graded contract is one whose assert reads a bare truthy flag that the
graph's OWN verifier node declares as an output: `verify` writes
`matches_ownership_map`, and the contract checks `output.matches_ownership_map`.
The model writes the flag it is scored on, so the check holds whenever the model
claims it does. Sixteen contracts across fifteen graphs were built this way, and
`validate._lint_self_graded` refuses them from agr/v1.8.

Two replacements, and neither is cosmetic:

1. **Cross-node comparison.** The verifier stops emitting a verdict and starts
   emitting a *measurement*, which is compared against a fact an upstream node
   already produced or the caller supplied. `assigned_team == expected_team` can
   still be satisfied by a model that makes both equal — but it has to name a
   team twice, in the trace, against a reference on the blackboard it did not
   write. That is a claim a reader can check; `matches_ownership_map: true` is not.

2. **An executable command.** Where the graph works on a real repository, the
   suite is the check. `verification[].command` runs it (opt-in via
   `--run-commands`) and the exit code is the fact. The registry had exactly one
   such command across 83 graphs, which is why every contract had to be a claim.

Six of the fifteen are the identical four-node router (`ticket-triage-swarm`,
`anomaly-investigation`, `incident-triage-router`, `clinical-literature-triage`,
`returns-triage`, `phishing-triage`) — the same graph in six domains. Fixing them
takes six different reference sets, which is exactly the domain difference the
shared topology was hiding.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import cases_path, load

# graph -> (reference input the caller supplies, decision key, example decision,
#           example reference value)
ROUTERS = {
    "ticket-triage-swarm": ("ownership_map", "assigned_queue", "billing-tier2"),
    "anomaly-investigation": ("holdout_labels", "assigned_class", "seasonal"),
    "incident-triage-router": ("ownership_map", "assigned_team", "platform-oncall"),
    "clinical-literature-triage": ("validated_labels", "assigned_evidence_level", "1b"),
    "returns-triage": ("policy_table", "assigned_disposition", "refund"),
    "phishing-triage": ("labeled_corpus", "assigned_verdict", "phish"),
}


def _set_outputs(node: dict, outs: list) -> None:
    node["outputs"] = outs


def fix_router(name: str) -> None:
    """The branch decides; the verifier reads the reference; the assert compares.

    Before: `verify` wrote `matches_<reference>` and the contract read it back.
    After: the branch nodes emit the decision, `verify` emits what the supplied
    reference says it should have been, and the contract compares two values that
    both appear in the trace.
    """
    ref, decision, example = ROUTERS[name]
    gpath = find_graph(name)
    doc = load(gpath)
    expected = "expected_" + decision.split("_", 1)[1]
    for n in doc["nodes"]:
        if n["id"].startswith("branch-"):
            _set_outputs(n, [decision])
        elif n.get("kind") == "verifier":
            _set_outputs(n, [expected, decision, "output"])
    doc["verification"] = [{
        "describe": f"the decision agrees with the {ref.replace('_', ' ')} the caller supplied",
        "assert": f"output.{decision} == output.{expected}",
    }, {
        "describe": "the reference was actually consulted, not left empty",
        "assert": f"len(output.{expected}) > 0",
    }]
    doc.setdefault("state", {}).setdefault("inputs", [])
    if ref not in doc["state"]["inputs"]:
        doc["state"]["inputs"].append(ref)
    gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))

    cpath = cases_path(name)
    data = yaml.safe_load(cpath.read_text())
    for case in data["cases"]:
        for nid in list(case["node_outputs"]):
            if nid.startswith("branch-"):
                case["node_outputs"][nid] = {decision: example}
            elif nid in ("verify",):
                case["node_outputs"][nid] = {
                    decision: example, expected: example,
                    "output": {decision: example, expected: example},
                }
        case.setdefault("inputs", {})[ref] = f"<{ref} supplied by the caller>"
    cpath.write_text(yaml.safe_dump(data, sort_keys=False, width=100))


#: graph -> (new verification list, {node_id: new outputs}, {node_id: case outputs})
INDIVIDUAL: dict[str, tuple] = {
    "vendor-comparison-matrix": (
        [{"describe": "no cell is uncited", "assert": "output.uncited_cells == 0"},
         {"describe": "every vendor row is scored on the criteria grid `normalize` produced",
          "assert": "all(all(c in output.criteria_grid for c in r.criteria) for r in output.matrix)"}],
        {"cite-check": ["criteria_grid", "matrix", "output", "uncited_cells"]},
        {"cite-check": {"criteria_grid": ["price", "sso"], "uncited_cells": 0,
                        "matrix": [{"criteria": ["price", "sso"], "vendor": "acme"}],
                        "output": {"uncited_cells": 0, "criteria_grid": ["price", "sso"],
                                   "matrix": [{"criteria": ["price", "sso"], "vendor": "acme"}]}}},
    ),
    "incident-lifecycle": (
        [{"describe": "the blast radius measured after mitigation is smaller than the one "
                      "`detect` measured before it",
          "assert": "output.residual_blast_radius < output.blast_radius"},
         {"describe": "the postmortem yields at least one owned action",
          "assert": "len(output.actions) >= 1 and all(a.owner for a in output.actions)"}],
        {"confirm": ["blast_radius", "residual_blast_radius"]},
        {"confirm": {"blast_radius": 12, "residual_blast_radius": 0}},
    ),
    "differential-diagnosis-ensemble": (
        [{"describe": "a consensus or a recorded disagreement, never neither",
          "assert": "output.consensus is not None or len(output.dissent) > 0"},
         {"describe": "every ranked hypothesis is represented in the adjudication — dissent "
                      "is carried, not averaged away",
          "assert": "all(r.clinician_id in output.represented for r in output.ranking)"}],
        {"adjudicate": ["consensus", "dissent", "output", "ranking", "represented"]},
        {"adjudicate": {"consensus": "PE", "dissent": ["ACS"], "represented": ["c1", "c2"],
                        "ranking": [{"clinician_id": "c1"}, {"clinician_id": "c2"}],
                        "output": {"consensus": "PE", "dissent": ["ACS"],
                                   "represented": ["c1", "c2"],
                                   "ranking": [{"clinician_id": "c1"}, {"clinician_id": "c2"}]}}},
    ),
    "onboarding-plan-builder": (
        [{"describe": "every checkpoint in the plan `draft-plan` produced carries a "
                      "markable milestone",
          "assert": "all(c.milestone for c in output.plan_30_60_90)"},
         {"describe": "every access request names the system and when it was raised",
          "assert": "all(a.system and a.requested_on for a in output.access_requests)"}],
        {"review": ["access_requests", "output", "plan_30_60_90"]},
        {"review": {"plan_30_60_90": [{"milestone": "ship one PR"}],
                    "access_requests": [{"system": "github", "requested_on": "2026-08-20"}],
                    "output": {"plan_30_60_90": [{"milestone": "ship one PR"}],
                               "access_requests": [{"system": "github",
                                                    "requested_on": "2026-08-20"}]}}},
    ),
    "supplier-risk-monitor": (
        [{"describe": "every supplier above appetite has a planned mitigation",
          "assert": "output.above_appetite == output.mitigations_planned"},
         {"describe": "the single-source flag agrees with the supplier count `concentrate` "
                      "measured, rather than being asserted",
          "assert": "all(c.single_source == (c.supplier_count == 1) for c in output.concentration)"}],
        {"mitigate": ["above_appetite", "concentration", "mitigations", "mitigations_planned",
                      "output"]},
        {"mitigate": {"above_appetite": 2, "mitigations_planned": 2, "mitigations": ["m1", "m2"],
                      "concentration": [{"single_source": True, "supplier_count": 1}],
                      "output": {"above_appetite": 2, "mitigations_planned": 2,
                                 "concentration": [{"single_source": True,
                                                    "supplier_count": 1}]}}},
    ),
    "red-team-blue-team-hardening": (
        [{"describe": "every bypass `attack` found points at the mitigation that closed it",
          "assert": "all(b.mitigation_ref for b in output.bypasses)"},
         {"describe": "nothing is left unmitigated",
          "assert": "output.unmitigated == 0"}],
        {"retest": ["bypasses", "output", "unmitigated"]},
        {"retest": {"unmitigated": 0, "bypasses": [{"mitigation_ref": "m-1"}],
                    "output": {"unmitigated": 0, "bypasses": [{"mitigation_ref": "m-1"}]}}},
    ),
    "vuln-remediation-lifecycle": (
        [{"describe": "the recorded proof-of-concept succeeded before the patch and fails "
                      "after it — proven by re-running it, not by inspecting the diff",
          "assert": "output.repro_exit_code_before == 0 and output.repro_exit_code_after != 0"},
         {"describe": "disclosure carries a human signature",
          "assert": "output.signed_off == true"},
         {"describe": "the advisory actually shipped",
          "assert": "output.advisory_published == true"}],
        {"prove": ["repro_exit_code_after", "repro_exit_code_before"],
         "reproduce": ["repro_confirmed", "repro_exit_code_before"]},
        # The human gate approved on `exploit_blocked` — the very flag the model
        # wrote. It now signs against the two exit codes, so the signature is on
        # evidence rather than on a claim.
        {"prove": {"repro_exit_code_before": 0, "repro_exit_code_after": 1},
         "reproduce": {"repro_confirmed": True, "repro_exit_code_before": 0}},
    ),
}

#: The suite IS the check on a graph that works in a real repository. These run
#: only under `--run-commands`; skipped commands are counted and reported, never
#: silently treated as passing.
COMMANDS = {
    "benchmark-driven-optimization-search": (
        [{"describe": "the retained candidate is faster than the baseline `profile` measured",
          "assert": "output.bench_ms < output.baseline_ms"},
         {"describe": "the suite is green — the exit code is the fact, not a claim about it",
          "command": "pytest -q"}],
        {"verify": ["baseline_ms", "bench_ms", "output"]},
        {"verify": {"bench_ms": 120, "baseline_ms": 400,
                    "output": {"bench_ms": 120, "baseline_ms": 400}}},
    ),
    "framework-migration": (
        [{"describe": "the suite is green on the target stack — checked by running it",
          "command": "pytest -q"},
         {"describe": "no slice is left unported",
          "assert": "output.slices_remaining == 0"}],
        {"integrate": ["ported_slices"]},
        {"integrate": {"ported_slices": 3}},
    ),
}


#: Downstream nodes that consumed a flag the verifier no longer emits, and the
#: fact they consume instead. A node's declared `inputs` are checked against what
#: reaches it, which is how removing a self-graded output surfaced these.
REWIRE = {
    "vuln-remediation-lifecycle": {
        "disclose-approval": {
            "inputs": ["repro_exit_code_after", "repro_exit_code_before"],
            "approval_contract": ("signed_off == true and repro_exit_code_before == 0 "
                                  "and repro_exit_code_after != 0"),
        },
    },
    "framework-migration": {
        "sign-off": {"inputs": ["ported_slices"]},
    },
}


def fix_individual(name: str, spec: tuple) -> None:
    verification, node_outputs, case_outputs = spec
    gpath = find_graph(name)
    doc = load(gpath)
    doc["verification"] = verification
    for nid, outs in node_outputs.items():
        node = next(n for n in doc["nodes"] if n["id"] == nid)
        _set_outputs(node, outs)
    for nid, rewire in REWIRE.get(name, {}).items():
        node = next(n for n in doc["nodes"] if n["id"] == nid)
        node["inputs"] = rewire["inputs"]
        if "approval_contract" in rewire:
            node["approval"]["contract"] = rewire["approval_contract"]
    gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))

    cpath = cases_path(name)
    data = yaml.safe_load(cpath.read_text())
    for case in data["cases"]:
        for nid, outs in case_outputs.items():
            existing = case["node_outputs"].get(nid) or {}
            merged = {**existing, **outs}
            merged["output"] = {**(existing.get("output") or {}), **(outs.get("output") or {})}
            case["node_outputs"][nid] = merged
    cpath.write_text(yaml.safe_dump(data, sort_keys=False, width=100))


#: A composite inherits its child's phase-tagged asserts, so rewriting a router's
#: contract rewrites the contract of every graph that embeds it. `incident-lifecycle`
#: embeds `incident-triage-router`; its fixtures carry the child's node outputs under
#: the phase prefix and must move with it. This is the coupling the v1.1 composites
#: were built for, showing up as maintenance for the first time.
COMPOSITE_PHASE_FIXTURES = {
    "incident-lifecycle": {
        "triage.branch-simple": {"assigned_team": "platform-oncall"},
        "triage.branch-complex": {},
        "triage.verify": {
            "owner": "owner-value", "severity": "severity-value",
            "assigned_team": "platform-oncall", "expected_team": "platform-oncall",
            "output": {"assigned_team": "platform-oncall",
                       "expected_team": "platform-oncall"},
        },
    },
}


def fix_composite_fixtures() -> int:
    n = 0
    for name, outs in COMPOSITE_PHASE_FIXTURES.items():
        cpath = cases_path(name)
        data = yaml.safe_load(cpath.read_text())
        for case in data["cases"]:
            for nid, out in outs.items():
                case["node_outputs"][nid] = out
            n += 1
        cpath.write_text(yaml.safe_dump(data, sort_keys=False, width=100))
    return n


def main() -> int:
    for name in ROUTERS:
        fix_router(name)
    for name, spec in {**INDIVIDUAL, **COMMANDS}.items():
        fix_individual(name, spec)
    cases = fix_composite_fixtures()
    print(f"realigned {cases} composite cases that embed a rewritten router")
    print(f"rewrote {len(ROUTERS)} router contracts and "
          f"{len(INDIVIDUAL) + len(COMMANDS)} individual contracts "
          f"({len(COMMANDS)} now checked by an executable command)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
