"""`agr eval` — run a graph's golden cases and write graphs/<...>/profile.json."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import yaml

from .harness import LLMRunner, MockRunner, ReplayRunner, run_graph
from .inspect import find_graph, structural_profile
from .registry import ROOT, SPEC_VERSION, cases_path, live_dir, load


def verification_depth(doc: dict, runner_name: str, grounded: bool = False) -> str:
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
        # `assert-grounded` is the first grade that distinguishes a true answer
        # from a plausible one: the assert held AND the values behind it trace to
        # a real tool call, not to the model's say-so.
        if grounded:
            return "assert-grounded"
        # `llm:` is a live endpoint, `llm-replay:` a checked-in recording of one.
        # Both are real model output; a fixture is not.
        return "assert-live" if runner_name.startswith(("llm", "tools")) else "assert-fixture"
    return "describe-only"


def _recordings(root: Path, name: str, case_id: str) -> list[Path]:
    """Every checked-in real-model run for this case, one per model.

    Recordings live in the graph's bundle at `live/<case>@<model>.json` (v1.2
    wrote a single <case>.json; both are read), falling back to the legacy
    `evals/<graph>/live/` tree. They are what makes `assert-live` reachable in
    CI: the depth grade shipped in v1.1 could report it, but producing it needed
    a network call, so no graph ever earned it.

    Several models matter because one weak model looks exactly like a bad
    contract. Only disagreement between models tells them apart.
    """
    live = live_dir(name, root)
    if not live.is_dir():
        return []
    # Two ways a recording stops counting, and both must be checked here rather
    # than trusted upstream:
    #
    # `superseded_by` is the explicit retirement — see
    # scripts/invalidate_recordings.py. The file is kept so a reader can see what
    # was measured; excluding it here is what stops a report quoting a number it
    # cannot stand behind.
    #
    # A missing or older `spec` is the implicit one. Recordings made before v1.8
    # did not say which spec they were scored against, which is exactly why all
    # 560 had to be invalidated wholesale instead of filtered. Requiring the field
    # means the next spec change can retire precisely what it invalidates.
    def current(p) -> bool:
        doc = json.loads(p.read_text())
        return not doc.get("superseded_by") and doc.get("spec") == SPEC_VERSION

    return sorted(p for p in live.glob(f"{case_id}*.json") if current(p))


def case_inputs(case: dict, goal: str | None = None) -> dict:
    """The blackboard a case supplies at entry.

    A case's `goal` is the common shape; `inputs` carries anything else the
    graph's `state.inputs` declares. An explicit `--goal` overrides the case, so
    one graph can be exercised against a real subject without editing fixtures.
    """
    seed = dict(case.get("inputs") or {})
    if case.get("goal"):
        seed["goal"] = case["goal"]
    if goal:
        seed["goal"] = goal
    return seed


def _without_clock(profile: dict) -> dict:
    """The profile minus the fields that change with the calendar and nothing else."""
    out = json.loads(json.dumps(profile))
    for block in ("measured", "measured_live"):
        if isinstance(out.get(block), dict):
            out[block].pop("date", None)
            out[block].pop("age_days", None)
    return out


def write_profile(gpath: Path, profile: dict) -> bool:
    """Write `profile.json` next to the graph, but only when its content changed.

    Returns True if a write happened. Before this, every caller of `eval_graph` —
    including the report generators — rewrote all 83 files with today's date, so
    `date` could never mean "when this evidence was captured" and a read-only
    audit had a hidden write side effect on the evidence store (2026-09-04 audit,
    D6-04). Now the date moves only when the profile behind it does.
    """
    target = gpath.parent / "profile.json"
    if target.exists():
        try:
            if _without_clock(json.loads(target.read_text())) == _without_clock(profile):
                return False
        except (ValueError, TypeError):
            pass  # unreadable on disk: rewrite it
    target.write_text(json.dumps(profile, indent=2) + "\n")
    return True


def eval_graph(name: str, root: Path = ROOT, live: bool = False,
               auto_approve: bool = False, run_commands: bool = False,
               replay: bool = True, resume_from=None, goal: str | None = None,
               write: bool = True) -> dict:
    """Run a graph's golden cases and return its profile.

    `write=True` persists the profile via `write_profile` (change-gated);
    `write=False` is a pure computation for report generators.
    """
    gpath = find_graph(name, root)
    if gpath is None:
        raise SystemExit(f"no graph named '{name}'")
    cases_file = cases_path(name, root)
    if not cases_file.exists():
        raise SystemExit(f"no eval cases at {cases_file.relative_to(root)} — write golden cases first")
    doc = load(gpath)
    cases = yaml.safe_load(cases_file.read_text())["cases"]

    def _run(runner, approve: bool | None = None, inputs: dict | None = None):
        rep = run_graph(doc, runner, root=root,
                        auto_approve=auto_approve if approve is None else approve,
                        run_commands=run_commands, resume_from=resume_from,
                        inputs=inputs)
        return {"passed": rep.passed, "steps": rep.steps, "trace": rep.trace,
                "goal_missing": rep.goal_missing,
                # Without this the diagnosis exists on the report and nowhere a
                # reader can see it: the profile said `AttributeError: <key>` for
                # eight graphs whose real fault was a terminal that never ran.
                "unreached_terminals": rep.unreached_terminals,
                "shape_violations": rep.shape_violations,
                "state_violations": rep.state_violations,
                "assert_failures": rep.assert_failures,
                "skipped_command_checks": rep.skipped_commands,
                "commands_run": rep.commands_run,
                "command_failures": rep.command_failures,
                "deadlocked": rep.deadlocked,
                "rejected_approvals": rep.rejected_approvals,
                "auto_approved": rep.auto_approved,
                "subgraphs_expanded": rep.expanded,
                "truncations": rep.truncations,
                "grounded": rep.grounded,
                "tool_calls": [
                    {"ability": c.ability, "ok": c.ok, "detail": c.detail}
                    for c in rep.tool_calls
                ]}

    def _block(results, runner_name):
        passed = sum(r["passed"] for r in results)
        return {
            "runner": runner_name,
            "provisional": runner_name == "mock",  # mock proves mechanics, not model quality
            "verification_depth": verification_depth(
                doc, runner_name, grounded=any(r.get("grounded") for r in results)),
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
        primary.append({"id": case["id"], **_run(runner, inputs=case_inputs(case, goal))})

    profile = structural_profile(doc, root)
    profile["measured"] = _block(primary, runner_name)

    # Secondary block: recorded real-model runs, reported SEPARATELY rather than
    # blended into the headline pass rate. Mixing them would let a graph that a
    # real model cannot satisfy hide inside an average, which is the exact
    # failure the depth grading exists to expose.
    if replay and not live:
        live_results = []
        for case in cases:
            for rec in _recordings(root, name, case["id"]):
                runner = ReplayRunner.load(rec)
                # A recording of a human-gated graph was necessarily made with the
                # gate auto-approved — a replay cannot sign anything. Honour that
                # here and stamp it, so the live result for such a graph is never
                # mistaken for evidence that the approval itself happened.
                gated = any(n.get("kind") == "human" for n in doc["nodes"])
                res = _run(runner, approve=gated or auto_approve,
                           inputs=case_inputs(case, goal))
                live_results.append({"id": case["id"], "model": runner.model,
                                     "recorded": runner.recorded,
                                     "gate_auto_approved": gated, **res})
        if live_results:
            models = sorted({r["model"] for r in live_results})
            block = _block(live_results, "llm-replay:" + ",".join(models))
            block["models"] = models
            block["recorded"] = min(r["recorded"] for r in live_results)
            block["age_days"] = (date.today() - date.fromisoformat(block["recorded"])).days
            per_model = {
                m: round(sum(r["passed"] for r in live_results if r["model"] == m)
                         / max(1, sum(1 for r in live_results if r["model"] == m)), 3)
                for m in models
            }
            block["per_model_pass_rate"] = per_model
            # Disagreement is the signal that separates a weak model from a bad
            # contract. Zero across the board would mean the extra models bought
            # nothing, so it is reported rather than averaged away.
            block["models_disagree"] = len(set(per_model.values())) > 1
            block["fails_every_model"] = all(v == 0.0 for v in per_model.values())
            # A model that both passes and fails the same graph across samples is
            # telling you something a single recording cannot: the result is a
            # coin flip, not a property. Reported separately from a clean pass so
            # "✅" never quietly means "passed once".
            block["flaky_models"] = sorted(
                m for m, rate in per_model.items() if 0.0 < rate < 1.0
            )
            block["samples_per_model"] = {
                m: sum(1 for r in live_results if r["model"] == m) for m in models
            }
            block["gate_auto_approved"] = any(r.get("gate_auto_approved") for r in live_results)
            profile["measured_live"] = block

    if write:
        write_profile(gpath, profile)
    return profile
