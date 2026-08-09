"""`agr eval` — run a graph's golden cases and write graphs/<...>/profile.json."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import yaml

from .harness import LLMRunner, MockRunner, ReplayRunner, run_graph
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
        # `llm:` is a live endpoint, `llm-replay:` a checked-in recording of one.
        # Both are real model output; a fixture is not.
        return "assert-live" if runner_name.startswith("llm") else "assert-fixture"
    return "describe-only"


def _recording(root: Path, name: str, case_id: str) -> Path | None:
    """A checked-in real-model run for this case, if one exists.

    Recordings live at evals/<graph>/live/<case>.json. They are what makes
    `assert-live` reachable in CI: the depth grade shipped in v1.1 could report
    it, but producing it needed a network call, so no graph ever earned it.
    """
    path = root / "evals" / name / "live" / f"{case_id}.json"
    return path if path.exists() else None


def eval_graph(name: str, root: Path = ROOT, live: bool = False,
               auto_approve: bool = False, run_commands: bool = False,
               replay: bool = True) -> dict:
    gpath = find_graph(name, root)
    if gpath is None:
        raise SystemExit(f"no graph named '{name}'")
    cases_file = root / "evals" / name / "cases.yaml"
    if not cases_file.exists():
        raise SystemExit(f"no eval cases at {cases_file.relative_to(root)} — write golden cases first")
    doc = load(gpath)
    cases = yaml.safe_load(cases_file.read_text())["cases"]

    def _run(runner):
        rep = run_graph(doc, runner, root=root, auto_approve=auto_approve,
                        run_commands=run_commands)
        return {"passed": rep.passed, "steps": rep.steps, "trace": rep.trace,
                "assert_failures": rep.assert_failures,
                "skipped_command_checks": rep.skipped_commands,
                "commands_run": rep.commands_run,
                "command_failures": rep.command_failures,
                "deadlocked": rep.deadlocked,
                "rejected_approvals": rep.rejected_approvals,
                "auto_approved": rep.auto_approved,
                "subgraphs_expanded": rep.expanded,
                "truncations": rep.truncations}

    def _block(results, runner_name):
        passed = sum(r["passed"] for r in results)
        return {
            "runner": runner_name,
            "provisional": runner_name == "mock",  # mock proves mechanics, not model quality
            "verification_depth": verification_depth(doc, runner_name),
            "date": date.today().isoformat(),
            "cases": len(results),
            "passed": passed,
            "pass_rate": round(passed / len(results), 3),
            "mean_steps": round(sum(r["steps"] for r in results) / len(results), 2),
            "results": results,
        }

    # Primary block: fixture mechanics (or a live endpoint when --live).
    primary, runner_name = [], "mock"
    for case in cases:
        runner = LLMRunner() if live else MockRunner(case["node_outputs"])
        runner_name = runner.name
        primary.append({"id": case["id"], **_run(runner)})

    profile = structural_profile(doc, root)
    profile["measured"] = _block(primary, runner_name)

    # Secondary block: recorded real-model runs, reported SEPARATELY rather than
    # blended into the headline pass rate. Mixing them would let a graph that a
    # real model cannot satisfy hide inside an average, which is the exact
    # failure the depth grading exists to expose.
    if replay and not live:
        live_results = []
        for case in cases:
            rec = _recording(root, name, case["id"])
            if rec is None:
                continue
            runner = ReplayRunner.load(rec)
            live_results.append({"id": case["id"], "model": runner.model,
                                 "recorded": runner.recorded, **_run(runner)})
        if live_results:
            block = _block(live_results, f"llm-replay:{live_results[0]['model']}")
            block["recorded"] = min(r["recorded"] for r in live_results)
            block["age_days"] = (date.today() - date.fromisoformat(block["recorded"])).days
            profile["measured_live"] = block

    (gpath.parent / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")
    return profile
