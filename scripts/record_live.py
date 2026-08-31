"""Record real-model node outputs into a graph's live/<case>.json.

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
from agenticgraphs.evalcmd import case_inputs
from agenticgraphs.harness import LLMRunner, ToolRunner, run_graph
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import ROOT, SPEC_VERSION, cases_path, live_dir, load


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

    def contract_for(self, node: dict) -> dict:
        """Forward the per-node contract, or the harness cannot reconcile output.

        Missing this made `_reconcile_output` a no-op during recording — it guards
        on `hasattr(runner, "contract_for")` — so a fix that worked on replay
        appeared to do nothing on the runs that produce the evidence.
        """
        return self.inner.contract_for(node)


def _model_dir(name: str, model: str) -> str:
    """Recordings are per-model: `<graph bundle>/live/<case>@<model>.json`.

    v1.2 kept one recording per case, which made a single weak model look like a
    property of the graph. Distinguishing "no model satisfies this contract" from
    "that one model was weak" needs several, kept side by side.
    """
    return model.replace("/", "-").replace(":", "-")


def record(name: str, sample: int = 0) -> list[dict]:
    """Record every golden case, not just the first one.

    This said `case = cases[0]` for the whole life of the project, so every live
    recording ever made exercised one branch per graph. "83 of 83 graphs recorded"
    always meant "one case each", and the cases most worth measuring are the ones
    written second — the branch a model gets wrong, the input that looks like one
    thing and routes to another. Those were never put to a model.

    The filename already carried the case id, and `_recordings` already globs by
    it, so the storage and replay sides were ready; only the loop was missing.
    """
    gpath = find_graph(name)
    doc = load(gpath)
    cases = yaml.safe_load((cases_path(name)).read_text())["cases"]
    return [_record_case(name, doc, case, sample) for case in cases]


def _record_case(name: str, doc: dict, case: dict, sample: int) -> dict:
    # AGR_TOOLS=1 binds each node's declared abilities; AGR_ALLOW_MUTATING=1 also
    # permits risk: write/execute, the same gate `agr eval --run-commands` uses.
    if os.environ.get("AGR_TOOLS") == "1":
        inner = ToolRunner(root=ROOT,
                           allow_mutating=os.environ.get("AGR_ALLOW_MUTATING") == "1")
    else:
        inner = LLMRunner()
    runner = RecordingRunner(inner)
    if hasattr(runner.inner, "report"):
        runner.inner.report = None  # set after RunReport exists, below
    # v1.7: seed the case's entry inputs. Without this a goal-required graph
    # refuses and records nothing — the recording would measure the gate rather
    # than the model. Same class of bug as a wrapper forwarding half an interface:
    # it fails silently and looks like a negative result.
    inputs = case_inputs(case)
    rep = run_graph(doc, runner, root=ROOT, auto_approve=True, inputs=inputs)
    out_dir = live_dir(name)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": os.environ["AGR_LLM_MODEL"],
        "recorded": date.today().isoformat(),
        "endpoint": os.environ["AGR_LLM_BASE_URL"],
        # The conditions the measurement was taken under. All 560 pre-v1.8
        # recordings had to be invalidated WHOLESALE rather than filtered, because
        # none of them said which spec version they were scored against or how the
        # model was sampled — so there was no way to tell a recording that survived
        # the prompt change from one that did not. A recording that cannot state
        # its own conditions cannot be re-validated later, only thrown away.
        "spec": SPEC_VERSION,
        "sampling": dict(LLMRunner.SAMPLING),
        # What the model was given. A recording that does not say what was on the
        # board cannot be compared against one made under different entry state.
        "inputs": inputs,
        "node_outputs": runner.captured,
        # Grounding is a property of the RUN, not of the node outputs. Without
        # carrying the trace, a replay of a tool-bound run grades `assert-live`
        # and the strongest evidence in the repo can never reach CI — the same
        # failure `assert-live` itself had before recordings existed.
        "tool_calls": [
            {"ability": c.ability, "args": c.args, "ok": c.ok, "detail": c.detail}
            for c in rep.tool_calls
        ],
    }
    model_tag = _model_dir(name, os.environ["AGR_LLM_MODEL"])
    # A second sample of the same graph+model is a different observation, not a
    # correction of the first: one recording per cell cannot distinguish a graph
    # that passes from one that passed by luck.
    suffix = f"@{model_tag}" + (f"#{sample}" if sample else "")
    (out_dir / f"{case['id']}{suffix}.json").write_text(json.dumps(payload, indent=2) + "\n")
    return {"graph": name, "case": case["id"], "passed": rep.passed,
            "steps": rep.steps, "failures": rep.assert_failures,
            "tool_calls": len(rep.tool_calls),
            "grounded": rep.grounded}


def _report(r: dict) -> None:
    if "error" in r:
        print(f"ERROR   {r['graph']}: {r['error']}", flush=True)
    else:
        mark = "PASS" if r["passed"] else "FAIL"
        tools = f" [{r.get('tool_calls', 0)} tool calls{', grounded' if r.get('grounded') else ''}]"
        print(f"{mark}    {r['graph']} ({r['steps']} steps){tools} {r['failures'] or ''}",
              flush=True)


def main() -> int:
    samples = int(os.environ.get("AGR_SAMPLES", "1"))
    for name in sys.argv[1:]:
        # Per SAMPLE, not per graph. Wrapping the whole loop meant one unparseable
        # reply discarded that graph's remaining samples — which is how a variance
        # run left three graphs at n=1, the exact condition it existed to remove.
        # A model that fails to emit JSON is itself an observation about the cell.
        for i in range(samples):
            try:
                results = record(name, sample=i)
            except Exception as ex:
                results = [{"graph": name, "error": f"{type(ex).__name__}: {ex}"}]
            # Reported as it happens, not accumulated. A 249-run sweep that batches
            # its output loses every result if the process is killed — which is
            # exactly what happened, and the recordings on disk were the only
            # surviving evidence of how far it got.
            for r in results:
                _report(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
