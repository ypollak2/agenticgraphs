"""Generate the AGR v1.2 graphs: search, ensemble, adversarial, reflexion, blackboard.

These are the first graphs in the registry that do something a fixed path cannot:
branch and score candidates, fan out over real shards and vote, or accumulate a
lesson between attempts. Each new motif gets at least one graph whose shape is
authored deliberately rather than stamped from a template — the v2 audit found
that count without diversity is how a library gets wide and stays shallow.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]

G: list[dict] = []


def g(**kw):
    G.append(kw)


def N(nid, spec, abil, outs, **extra):
    n = {"id": nid, "speciality": spec, "abilities": list(abil)}
    if outs:
        n["outputs"] = list(outs)
    n.update(extra)
    return n


# --- tree-search -------------------------------------------------------------

g(final={"bench_ms": 120, "baseline_ms": 400, "suite_green": True}, name="benchmark-driven-optimization-search", domain="software-engineering",
  motif="tree-search",
  summary="Branch candidate optimizations, score each on a real benchmark, keep the beam, prune the rest.",
  nodes=[
    N("profile", "analyst", ["analyze"], ["hotspot", "baseline_ms"], inputs=["repo"]),
    N("explore", "producer", ["generate"], ["patch", "bench_ms"], inputs=["hotspot"],
      kind="search",
      search={"branch": 4, "depth": 3, "score": "bench_ms", "objective": "min",
              "prune": "beam(2)"}),
    N("verify", "qa-lead", ["run_suite"], ["suite_green", "output"], inputs=["patch"],
      kind="verifier"),
  ],
  edges=[("profile", "explore"), ("explore", "verify")],
  checks=[("the winning candidate actually beats the baseline",
           "output.bench_ms < output.baseline_ms"),
          ("and does not do it by breaking the suite", "output.suite_green == true")],
  contract="the retained candidate is faster than baseline with a green suite; losers are pruned, not shipped",
  steps=40, state_inputs=["repo"])

g(final={"holdout_score": 0.81, "baseline_score": 0.72}, name="prompt-graph-optimization", domain="research-knowledge", motif="tree-search",
  summary="Search prompt-and-topology variants against a held-out eval set, keeping only measured winners.",
  nodes=[
    N("baseline", "evaluator", ["evaluate"], ["baseline_score", "eval_set"], inputs=["graph_under_test"]),
    N("search", "producer", ["generate"], ["variant", "score"], inputs=["eval_set"],
      kind="search",
      search={"branch": 3, "depth": 3, "score": "score", "objective": "max",
              "prune": "beam(2)"}),
    N("confirm", "verifier", ["run_command"], ["holdout_score", "output"], inputs=["variant"],
      kind="verifier"),
  ],
  edges=[("baseline", "search"), ("search", "confirm")],
  checks=[("the winner is confirmed on held-out data, not the set it was tuned on",
           "output.holdout_score > output.baseline_score")],
  contract="a variant ships only if it beats baseline on a held-out set it was not searched against",
  steps=40, state_inputs=["graph_under_test"])

# --- ensemble-quorum ---------------------------------------------------------

g(final={"consensus": "dx-a", "dissent": [{"dx": "dx-b"}], "dissent_retained": True}, name="differential-diagnosis-ensemble", domain="healthcare-science", motif="ensemble-quorum",
  summary="Independent diagnosticians rank hypotheses; a quorum decides and dissent is reported, never dropped.",
  nodes=[
    N("intake", "analyst", ["analyze"], ["presentations"], inputs=["case_notes"]),
    N("diagnose", "analyst", ["analyze"], ["ranking"], inputs=["presentations"],
      fan_out={"over": "presentations", "max": 5, "on_partial": "continue"}),
    N("adjudicate", "judge", ["adjudicate"], ["consensus", "dissent", "output"],
      inputs=["ranking"], join="quorum(1)",
      aggregate={"op": "majority", "over": "ranking"}, kind="verifier"),
  ],
  edges=[("intake", "diagnose"), ("diagnose", "adjudicate")],
  checks=[("a tie is surfaced as no-consensus, never resolved by coin flip",
           "output.consensus is not None or len(output.dissent) > 0"),
          ("every dissenting opinion is retained", "output.dissent_retained == true")],
  contract="a diagnosis carries its quorum; disagreement is reported rather than averaged away",
  steps=30, state_inputs=["case_notes"])

g(final={"segments_scored": 6, "variance": 0.14, "final_score": 78}, name="sales-call-scorer", domain="customer-support-sales", motif="ensemble-quorum",
  summary="Score a call against a rubric from several independent passes, reporting variance as a confidence signal.",
  nodes=[
    N("segment", "mapper", ["map_shard"], ["segments"], inputs=["transcript"]),
    N("score-pass", "evaluator", ["evaluate"], ["rubric_score"], inputs=["segments"],
      fan_out={"over": "segments", "max": 12}),
    N("consolidate", "reducer", ["reduce_merge"], ["final_score", "variance", "output"],
      inputs=["rubric_score"], aggregate={"op": "median", "over": "rubric_score"},
      kind="verifier"),
  ],
  edges=[("segment", "score-pass"), ("score-pass", "consolidate")],
  checks=[("every scored segment is traceable", "output.segments_scored >= 1"),
          ("disagreement between passes is reported, not hidden",
           "output.variance is not None")],
  contract="the score reports the spread between passes alongside the median",
  steps=30, state_inputs=["transcript"])

# --- red-team / blue-team ----------------------------------------------------

g(final={"attacker_exhausted": True, "unmitigated": 0}, name="red-team-blue-team-hardening", domain="security", motif="red-team-blue-team",
  summary="An attacker searches for a working bypass while a defender patches, until the attacker is exhausted.",
  nodes=[
    N("scope", "analyst", ["analyze"], ["surface", "rules_of_engagement"], inputs=["target"]),
    N("attack", "security-auditor", ["sast_scan", "read_diff"], ["bypass", "severity"],
      inputs=["surface"], kind="search",
      search={"branch": 4, "depth": 2, "score": "severity", "objective": "max",
              "prune": "beam(2)"}),
    N("defend", "executor", ["execute_step", "edit_files"], ["mitigation"], inputs=["bypass"]),
    N("retest", "verifier", ["run_command"], ["attacker_exhausted", "output"],
      inputs=["mitigation"], kind="verifier"),
  ],
  edges=[("scope", "attack"), ("attack", "defend"), ("defend", "retest"),
         ("retest", "attack", "not attacker_exhausted and attempts < 3")],
  checks=[("the run ends only when the attacker can no longer find a bypass",
           "output.attacker_exhausted == true"),
          ("every bypass found is either mitigated or explicitly accepted",
           "output.unmitigated == 0")],
  contract="terminates on attacker exhaustion, producing evidence of absence rather than absence of evidence",
  steps=45, state_inputs=["target"])

# --- reflexion ---------------------------------------------------------------

g(final={"consecutive_green": 3, "lessons": [{"tried": "seed pinning"}]}, name="flaky-test-reflexion", domain="software-engineering", motif="reflexion",
  summary="Re-run a suspected flake, write down what was learned each time, and use it on the next attempt.",
  nodes=[
    N("reproduce", "worker", ["run_command"], ["observed", "seed"], inputs=["test_id"]),
    N("hypothesise", "analyst", ["analyze"], ["hypothesis"], inputs=["observed", "lessons"]),
    N("test-fix", "executor", ["execute_step", "edit_files"], ["candidate_fix"], inputs=["hypothesis"]),
    N("evaluate", "evaluator", ["evaluate"], ["stable", "lessons", "output"],
      inputs=["candidate_fix"], kind="verifier"),
  ],
  edges=[("reproduce", "hypothesise"), ("hypothesise", "test-fix"), ("test-fix", "evaluate"),
         ("evaluate", "hypothesise", "not stable and attempts < 4")],
  checks=[("the test is stable across repeated runs, not merely green once",
           "output.consecutive_green >= 3"),
          ("each failed attempt left a lesson behind", "len(output.lessons) >= 1")],
  contract="stability is proven over repeated runs, and every failed attempt is recorded as a lesson",
  steps=40, state_inputs=["test_id"], memory={"scope": "graph"})

g(final={"pipeline_green": True, "escalated": False, "lessons": [{"tried": "cache clear"}]}, name="self-healing-ci", domain="devops-sre", motif="reflexion",
  summary="Diagnose a red pipeline, attempt a bounded repair, and accumulate what did not work across runs.",
  nodes=[
    N("collect", "sre", ["run_command"], ["failures"], inputs=["pipeline_run"]),
    N("classify", "analyst", ["analyze"], ["cause", "known"], inputs=["failures", "lessons"]),
    N("repair", "executor", ["execute_step"], ["repair_applied"], inputs=["cause"]),
    N("confirm", "verifier", ["run_command"], ["pipeline_green", "lessons", "output"],
      inputs=["repair_applied"], kind="verifier"),
  ],
  edges=[("collect", "classify"), ("classify", "repair"), ("repair", "confirm"),
         ("confirm", "classify", "not pipeline_green and attempts < 3")],
  checks=[("the pipeline is green, or the failure is escalated with its history",
           "output.pipeline_green == true or output.escalated == true"),
          ("nothing is retried blind", "len(output.lessons) >= 1")],
  contract="a red pipeline ends green or escalated, never retried without a recorded reason",
  steps=35, state_inputs=["pipeline_run"], memory={"scope": "graph"})

# --- blackboard --------------------------------------------------------------

g(final={"uncited_claims": 0, "open_questions": []}, name="forensic-investigation-blackboard", domain="security", motif="blackboard",
  summary="Specialists contribute independently to shared evidence; a controller decides when the picture closes.",
  nodes=[
    N("seed", "analyst", ["analyze"], ["leads"], inputs=["incident"]),
    N("investigate", "security-auditor", ["sast_scan", "run_command", "read_diff"], ["evidence"],
      inputs=["leads"], fan_out={"over": "leads", "max": 8}),
    N("assess", "judge", ["adjudicate"], ["picture", "open_questions", "output"],
      inputs=["evidence"], aggregate={"op": "union", "over": "evidence"}, kind="verifier"),
  ],
  edges=[("seed", "investigate"), ("assess", "investigate", "len(open_questions) > 0 and attempts < 3"),
         ("investigate", "assess")],
  checks=[("every conclusion cites the evidence it rests on", "output.uncited_claims == 0"),
          ("open questions are listed rather than quietly closed",
           "output.open_questions is not None")],
  contract="conclusions cite evidence; unresolved questions are stated, not dropped",
  steps=40, state_inputs=["incident"])

# --- tournament --------------------------------------------------------------

g(final={"designs_scored": 3, "margin": 0.18, "winner": "option-b"}, name="architecture-decision-tournament", domain="software-engineering", motif="tournament",
  summary="Independent designs are scored on one rubric, and the winner must beat the runner-up on record.",
  nodes=[
    N("frame", "analyst", ["analyze"], ["options", "rubric"], inputs=["decision"]),
    N("design", "advocate", ["generate"], ["proposal", "rubric_score"], inputs=["options"],
      fan_out={"over": "options", "max": 6}),
    N("judge", "judge", ["adjudicate"], ["winner", "margin", "output"],
      inputs=["proposal", "rubric_score"], aggregate={"op": "best", "over": "rubric_score"},
      kind="verifier"),
  ],
  edges=[("frame", "design"), ("design", "judge")],
  checks=[("at least three designs were scored on the same rubric",
           "output.designs_scored >= 3"),
          ("the decision records why the runner-up lost", "output.margin is not None")],
  contract="a decision names its runner-up and the margin, so it can be revisited on evidence",
  steps=30, state_inputs=["decision"])


def build(spec: dict) -> dict:
    edges = []
    for e in spec["edges"]:
        d = {"from": e[0], "to": e[1]}
        if len(e) > 2:
            d["when"] = e[2]
        edges.append(d)
    doc = {
        "apiVersion": "agr/v1.2",
        "name": spec["name"],
        "description": spec["summary"],
        "category": spec["domain"],
        "nodes": spec["nodes"],
        "edges": edges,
        "termination": {"max_steps": spec["steps"], "contract": spec["contract"]},
        "verification": [{"describe": d, "assert": a} for d, a in spec["checks"]],
    }
    if spec.get("state_inputs"):
        doc["state"] = {"inputs": spec["state_inputs"]}
    if spec.get("memory"):
        doc["memory"] = spec["memory"]
    return doc


#: Values that steer a v1.2 execution rather than merely being read: a fan-out
#: needs a real list to iterate, and a search needs a scoreable candidate.
_DRIVERS = {
    "presentations": [{"p": 1}, {"p": 2}, {"p": 3}],
    "segments": [{"s": 1}, {"s": 2}], "leads": [{"l": 1}, {"l": 2}],
    "options": [{"o": "a"}, {"o": "b"}, {"o": "c"}],
    "bench_ms": 120, "score": 0.81, "severity": 2, "rubric_score": 7,
    "attacker_exhausted": True, "stable": True, "pipeline_green": True,
    "open_questions": [], "suite_green": True,
}


def cases_for(spec: dict, doc: dict) -> dict:
    """Fixtures that both satisfy the contract and actually drive the new machinery.

    A v1.1 composite could be fixtured from its declared outputs alone. A v1.2
    graph cannot: fan-out iterates a real list and search scores a real
    candidate, so a fixture of plausible scalars would execute zero shards and
    zero branches while still reporting a pass.
    """
    outs: dict[str, dict] = {}
    for n in doc["nodes"]:
        vals: dict = {}
        for k in n.get("outputs") or []:
            if k == "output":
                continue
            vals[k] = _DRIVERS.get(k, spec["final"].get(k, f"{k}-value"))
        outs[n["id"]] = vals
    terminal = doc["nodes"][-1]["id"]
    outs.setdefault(terminal, {})["output"] = spec["final"]
    outs[terminal].update({k: v for k, v in spec["final"].items() if k in _DRIVERS})
    return {"cases": [{"id": "happy-path", "node_outputs": outs}]}


def main() -> None:
    for spec in G:
        doc = build(spec)
        out = ROOT / "graphs" / spec["domain"] / spec["name"] / "graph.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
        ev = ROOT / "evals" / spec["name"] / "cases.yaml"
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text(yaml.safe_dump(cases_for(spec, doc), sort_keys=False, width=100))
    total = len(list((ROOT / "graphs").glob("*/*/graph.yaml")))
    print(f"wrote {len(G)} v1.2 graphs; registry now {total}")


if __name__ == "__main__":
    main()
