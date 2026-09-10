#!/usr/bin/env python3
"""A/B whether AGR v1.9 edge guidance actually improves live pass rates.

    AGR_LLM_BASE_URL=http://localhost:11434/v1 AGR_LLM_MODEL=qwen3-coder:30b \
      python scripts/guidance_ab.py --graphs blog-production-pipeline --episodes 3

Why this cannot be a replay experiment
--------------------------------------
`_live_score` gates the optimizer by replaying recorded `node_outputs` against a
mutated graph. That works for topology because topology decides which nodes run.
It cannot work here: guidance changes what a node is *told*, and a recording's
outputs are fixed, so both arms replay identically. Measuring guidance requires
real inference, one call per node per arm.

The decision rule is fixed here, in code, before any run — so a disappointing
result cannot be rescued by moving the line afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agenticgraphs.evalcmd import case_inputs                      # noqa: E402
from agenticgraphs.harness import LLMRunner, run_graph             # noqa: E402
from agenticgraphs.inspect import find_graph                       # noqa: E402
from agenticgraphs.registry import ROOT, cases_path, load          # noqa: E402

# ---------------------------------------------------------------------------
# Pre-registered decision rule. Do not edit after data collection begins.
# ---------------------------------------------------------------------------
CRITERIA = {
    "min_mean_delta": 0.25,
    # Two arms that differ by less than this on a single graph are one coin flip
    # apart. docs/milestones.md records two graphs that returned both a pass and
    # a fail under identical input, so a per-graph win under this margin is noise.
    "min_per_graph_delta": 0.34,
    "min_graphs_improved": 6,      # of 11 — a majority, not one graph carrying it
    "max_graphs_regressed": 2,
    "require_zero_leaks": True,
    "episodes_per_arm": 3,
}


def audit_leak(doc: dict) -> list[str]:
    """Reject guidance that hands the model the answer it is scored on.

    This is the v1.6/T7 failure with a new coat of paint. If guidance says
    "return designs_scored = 3" and the assert reads `output.designs_scored >= 3`,
    a pass measures echo, not improvement. Any identifier or literal shared
    between an edge's prose and the graph's own asserts is a leak.
    """
    asserts = " ".join(str(v.get("assert", "")) for v in (doc.get("verification") or []))
    if not asserts.strip():
        return []
    # Identifiers the asserts actually score on, minus python/DSL noise words.
    noise = {"and", "or", "not", "in", "for", "if", "else", "all", "any", "len",
             "true", "false", "none", "output", "sum", "min", "max", "abs", "int"}
    scored = {t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", asserts)
              if t.lower() not in noise and len(t) > 3}
    numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", asserts))
    leaks = []
    for e in doc.get("edges") or []:
        prose = " ".join(str(e.get(k, "")) for k in ("guidance", "condition", "pitfalls"))
        if not prose.strip():
            continue
        words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", prose))
        for hit in sorted(scored & words):
            leaks.append(f"{e['from']}->{e['to']}: names asserted identifier '{hit}'")
        for n in sorted(numbers & set(re.findall(r"\b\d+(?:\.\d+)?\b", prose))):
            leaks.append(f"{e['from']}->{e['to']}: repeats asserted literal '{n}'")
    return leaks


def strip_guidance(doc: dict) -> dict:
    out = json.loads(json.dumps(doc))
    for e in out.get("edges") or []:
        for k in ("guidance", "condition", "pitfalls"):
            e.pop(k, None)
    return out


def run_arm(doc: dict, name: str, episodes: int) -> dict:
    """Run every golden case `episodes` times; return pass rate and diagnostics."""
    cases = yaml.safe_load(cases_path(name, ROOT).read_text())["cases"]
    gated = any(n.get("kind") == "human" for n in doc["nodes"])
    results = []
    for case in cases:
        for ep in range(episodes):
            runner = LLMRunner()
            # Paired sampling: arm A and arm B see the same seed for the same
            # episode, so the only difference between them is the prompt.
            runner.SAMPLING = {**LLMRunner.SAMPLING, "seed": 7 + ep}
            try:
                rep = run_graph(doc, runner, root=ROOT, auto_approve=gated,
                                inputs=case_inputs(case))
                results.append({"case": case["id"], "episode": ep, "passed": bool(rep.passed),
                                "steps": rep.steps, "failure_kinds": rep.failure_kinds,
                                "assert_failures": [str(a)[:120] for a in rep.assert_failures]})
            except Exception as exc:  # a crash is a failure, not a missing datapoint
                results.append({"case": case["id"], "episode": ep, "passed": False,
                                "steps": 0, "failure_kinds": ["error"],
                                "assert_failures": [type(exc).__name__ + ": " + str(exc)[:100]]})
    n = len(results)
    return {"pass_rate": round(sum(r["passed"] for r in results) / n, 3) if n else 0.0,
            "n": n, "results": results}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graphs", nargs="+", required=True)
    ap.add_argument("--episodes", type=int, default=CRITERIA["episodes_per_arm"])
    ap.add_argument("--out", default="reports/guidance-ab.json")
    args = ap.parse_args()

    if not os.environ.get("AGR_LLM_BASE_URL"):
        print("set AGR_LLM_BASE_URL and AGR_LLM_MODEL first", file=sys.stderr)
        return 2

    report = {"model": os.environ.get("AGR_LLM_MODEL"), "date": date.today().isoformat(),
              "criteria": CRITERIA, "episodes_per_arm": args.episodes, "graphs": {}}

    for name in args.graphs:
        gp = find_graph(name, ROOT)
        if gp is None:
            print(f"skip {name}: not found", file=sys.stderr)
            continue
        withg = load(gp)
        if not any(e.get(k) for e in (withg.get("edges") or [])
                   for k in ("guidance", "condition", "pitfalls")):
            print(f"skip {name}: declares no edge guidance — nothing to A/B", file=sys.stderr)
            continue
        leaks = audit_leak(withg)
        without = strip_guidance(withg)
        print(f"[{name}] leak audit: {len(leaks)} finding(s)", file=sys.stderr)
        off = run_arm(without, name, args.episodes)
        print(f"[{name}] guidance OFF: {off['pass_rate']} (n={off['n']})", file=sys.stderr)
        on = run_arm(withg, name, args.episodes)
        print(f"[{name}] guidance ON : {on['pass_rate']} (n={on['n']})", file=sys.stderr)
        report["graphs"][name] = {"leaks": leaks, "off": off, "on": on,
                                  "delta": round(on["pass_rate"] - off["pass_rate"], 3)}

    g = report["graphs"]
    if g:
        deltas = [v["delta"] for v in g.values()]
        leaks_total = sum(len(v["leaks"]) for v in g.values())
        improved = sum(1 for d in deltas if d >= CRITERIA["min_per_graph_delta"])
        regressed = sum(1 for d in deltas if d <= -CRITERIA["min_per_graph_delta"])
        verdict = {
            "mean_delta": round(statistics.mean(deltas), 3),
            "graphs": len(deltas), "improved": improved, "regressed": regressed,
            "leaks_total": leaks_total,
            "passes": (statistics.mean(deltas) >= CRITERIA["min_mean_delta"]
                       and improved >= CRITERIA["min_graphs_improved"]
                       and regressed <= CRITERIA["max_graphs_regressed"]
                       and (leaks_total == 0 or not CRITERIA["require_zero_leaks"])),
        }
        report["verdict"] = verdict
        print("\n=== VERDICT ===")
        print(json.dumps(verdict, indent=2))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
