"""Record real-model node outputs into evals/<graph>/live/<case>.json.

The depth grading shipped in v1.1 could report `assert-live`, but nothing ever
produced it: a live run needs a network call, so CI never made one and all 74
graphs stayed at `assert-fixture`. A recording is one real model run, captured
and checked in, so the assert is graded against what a model actually said.

Recordings are evidence with a shelf life — each stamps the model and date, and
the scoreboard shows the age. A recording whose asserts FAIL is still recorded:
a contract a real model cannot satisfy is exactly the finding this is for, and
deleting it would restore the comfortable fiction the fixture depth already gives.

    AGR_LLM_BASE_URL=http://localhost:11434/v1 AGR_LLM_MODEL=qwen2.5-coder:7b \\
        uv run python scripts/record_live.py quiz-generation-verified ...
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.harness import LLMRunner, run_graph  # noqa: E402
from agenticgraphs.inspect import find_graph  # noqa: E402
from agenticgraphs.registry import ROOT, load  # noqa: E402


class RecordingRunner:
    """Wraps LLMRunner and captures every node output verbatim."""

    def __init__(self, inner):
        self.inner, self.captured = inner, {}
        self.name = inner.name

    def run(self, node: dict, bb: dict) -> dict:
        out = self.inner.run(node, bb)
        prior = self.captured.get(node["id"])
        if prior is None:
            self.captured[node["id"]] = out
        elif isinstance(prior, list):
            prior.append(out)
        else:
            self.captured[node["id"]] = [prior, out]
        return out

    def approve(self, node: dict, bb: dict, auto_approve: bool = False):
        return self.inner.approve(node, bb, auto_approve=auto_approve)

    def bind(self, doc: dict) -> None:
        self.inner.bind(doc)


def record(name: str) -> dict:
    gpath = find_graph(name)
    doc = load(gpath)
    cases = yaml.safe_load((ROOT / "evals" / name / "cases.yaml").read_text())["cases"]
    case = cases[0]
    runner = RecordingRunner(LLMRunner())
    rep = run_graph(doc, runner, root=ROOT, auto_approve=True)
    out_dir = ROOT / "evals" / name / "live"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": os.environ["AGR_LLM_MODEL"],
        "recorded": date.today().isoformat(),
        "endpoint": os.environ["AGR_LLM_BASE_URL"],
        "node_outputs": runner.captured,
    }
    (out_dir / f"{case['id']}.json").write_text(json.dumps(payload, indent=2) + "\n")
    return {"graph": name, "case": case["id"], "passed": rep.passed,
            "steps": rep.steps, "failures": rep.assert_failures}


def main() -> int:
    results = []
    for name in sys.argv[1:]:
        try:
            results.append(record(name))
        except Exception as ex:  # noqa: BLE001 — a failed recording is a result, not a crash
            results.append({"graph": name, "error": f"{type(ex).__name__}: {ex}"})
    for r in results:
        if "error" in r:
            print(f"ERROR   {r['graph']}: {r['error']}")
        else:
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"{mark}    {r['graph']} ({r['steps']} steps) {r['failures'] or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
