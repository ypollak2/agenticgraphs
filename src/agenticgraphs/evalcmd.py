"""`agr eval` — run a graph's golden cases and write graphs/<...>/profile.json."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import yaml

from .harness import LLMRunner, MockRunner, run_graph
from .inspect import find_graph, structural_profile
from .registry import ROOT, load


def verification_depth(doc: dict, runner_name: str) -> str:
    """How strong is this graph's evidence, honestly graded.

    `assert-fixture` is the level almost every graph sits at: the assert held
    against a mock fixture written alongside the graph. That proves the graph
    routes the key through — not that the claim was earned. Grading it makes the
    scoreboard say so instead of reporting a flat 100%.
    """
    checks = doc.get("verification") or []
    if any("command" in v for v in checks):
        return "command"  # only reachable when the caller opted into execution
    if any("assert" in v for v in checks):
        return "assert-live" if runner_name.startswith("llm") else "assert-fixture"
    return "describe-only"


def eval_graph(name: str, root: Path = ROOT, live: bool = False,
               auto_approve: bool = False, run_commands: bool = False) -> dict:
    gpath = find_graph(name, root)
    if gpath is None:
        raise SystemExit(f"no graph named '{name}'")
    cases_file = root / "evals" / name / "cases.yaml"
    if not cases_file.exists():
        raise SystemExit(f"no eval cases at {cases_file.relative_to(root)} — write golden cases first")
    doc = load(gpath)
    cases = yaml.safe_load(cases_file.read_text())["cases"]
    results, runner_name = [], None
    for case in cases:
        runner = LLMRunner() if live else MockRunner(case["node_outputs"])
        runner_name = runner.name
        rep = run_graph(doc, runner, root=root, auto_approve=auto_approve,
                        run_commands=run_commands)
        results.append({"id": case["id"], "passed": rep.passed, "steps": rep.steps,
                        "trace": rep.trace, "assert_failures": rep.assert_failures,
                        "skipped_command_checks": rep.skipped_commands,
                        "commands_run": rep.commands_run,
                        "command_failures": rep.command_failures,
                        "deadlocked": rep.deadlocked,
                        "rejected_approvals": rep.rejected_approvals,
                        "auto_approved": rep.auto_approved,
                        "subgraphs_expanded": rep.expanded})
    passed = sum(r["passed"] for r in results)
    profile = structural_profile(doc, root)
    profile["measured"] = {
        "runner": runner_name,
        "provisional": runner_name == "mock",  # mock proves mechanics, not model quality
        "verification_depth": verification_depth(doc, runner_name or "mock"),
        "date": date.today().isoformat(),
        "cases": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 3),
        "mean_steps": round(sum(r["steps"] for r in results) / len(results), 2),
        "results": results,
    }
    (gpath.parent / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    return profile
