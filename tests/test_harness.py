import pytest
import yaml

from agenticgraphs.evalcmd import eval_graph
from agenticgraphs.harness import MockRunner, run_graph, safe_eval
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import ROOT, cases_path, load

#: Every graph declares `goal.required` as of v1.8, so a direct `run_graph` must
#: supply one or the graph refuses before scheduling a node — which is the gate
#: working, not a broken test. Golden cases carry their own goal; these
#: hand-built runs need one stated here.
GOAL = {"goal": "a stated subject, so the graph does not invent one"}


def test_level_conditions():
    assert safe_eval("risk >= medium", {"risk": "high"})
    assert not safe_eval("risk >= medium", {"risk": "low"})
    assert safe_eval("complexity <= moderate", {"complexity": "simple"})


def test_router_takes_single_branch():
    doc = load(find_graph("cost-routed-research"))
    rep = run_graph(doc, MockRunner({
        "router": {"complexity": "complex"},
        "deep-researcher": {"confidence": 0.9},
        "synthesizer": {"output": {"claims": [{"text": "t", "sources": ["s"]}]}},
    }), inputs=GOAL)
    assert rep.passed and "cheap-researcher" not in rep.trace


def test_loop_bounded_and_escalation_detected():
    doc = load(find_graph("verifier-swarm"))
    cases = yaml.safe_load((cases_path("verifier-swarm")).read_text())["cases"]
    retry = next(c for c in cases if c["id"] == "retry-then-verified")
    rep = run_graph(doc, MockRunner(retry["node_outputs"]), inputs=GOAL)
    assert rep.passed and rep.trace.count("worker") == 2


def test_verification_failure_is_caught():
    doc = load(find_graph("code-review-pipeline"))
    rep = run_graph(doc, MockRunner({
        "triage": {"risk": "low"},
        "style-review": {},
        "synthesize": {"output": {"verdict": "merged!!", "findings": []}},
    }), inputs=GOAL)
    assert not rep.passed and rep.assert_failures


@pytest.mark.parametrize("name", ["code-review-pipeline", "verifier-swarm", "cost-routed-research"])
def test_eval_writes_passing_provisional_profile(name):
    profile = eval_graph(name)
    m = profile["measured"]
    assert m["pass_rate"] == 1.0 and m["provisional"] is True and m["runner"] == "mock"
    assert (find_graph(name).parent / "profile.json").exists()
