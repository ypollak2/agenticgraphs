"""AGR v1.2: frames, fan-out, aggregation, bounded search, phase-scoped verification.

The theme of v1.2 is that the blackboard gained a history. Every test below is
downstream of that: a frame is what one node execution wrote, and phase
verification, real fan-out and search results are all projections over frames.
"""
from __future__ import annotations

import json

import pytest
import yaml

from agenticgraphs.harness import MockRunner, ReplayRunner, run_graph
from agenticgraphs.registry import ROOT, iter_graphs, load
from agenticgraphs.subgraphs import expand
from agenticgraphs.validate import lint_graph, validate_graph_file, validate_schema


def _g(**kw):
    doc = {
        "apiVersion": "agr/v1.2",
        "name": "unit-test-graph",
        "description": "a graph used only by unit tests",
        "category": "software-engineering",
        "nodes": [
            {"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
            {"id": "b", "speciality": "producer", "abilities": ["generate"]},
        ],
        "edges": [{"from": "a", "to": "b"}],
        "termination": {"max_steps": 20, "contract": "b runs after a"},
    }
    doc.update(kw)
    return doc


class _Shards:
    """Runner that echoes the shard it was handed, so fan-out is observable."""

    name = "mock"

    def __init__(self, seed=None):
        self.seed, self.calls = seed or {}, 0

    def run(self, node, bb):
        self.calls += 1
        if "shard" in bb:
            return {"score": bb["shard"] * 10, "seen": bb["shard_index"]}
        return dict(self.seed)


# ------------------------------------------------------------------------ frames


def test_every_node_execution_leaves_a_frame():
    rep = run_graph(_g(), MockRunner({"a": {"x": 1}, "b": {"y": 2}}))
    assert [f["node"] for f in rep.frames] == ["a", "b"]
    assert rep.frames[0]["out"] == {"x": 1}


def test_frames_record_each_visit_of_a_looping_node():
    doc = _g(
        nodes=[{"id": "attempt", "speciality": "producer", "abilities": ["generate"]},
               {"id": "check", "speciality": "evaluator", "abilities": ["evaluate"],
                "kind": "verifier"}],
        edges=[{"from": "attempt", "to": "check"},
               {"from": "check", "to": "attempt", "when": "retry and attempts < 3"}],
        verification=[{"assert": "attempts >= 1"}],
    )
    rep = run_graph(doc, MockRunner({"attempt": {}, "check": {"retry": True}}))
    assert len(rep.frames_for("attempt")) == 3


# ----------------------------------------------------------------------- fan-out


def _fanned(max_n=40, on_partial="continue"):
    return _g(
        nodes=[
            {"id": "split", "speciality": "analyst", "abilities": ["analyze"],
             "outputs": ["shards"]},
            {"id": "work", "speciality": "mapper", "abilities": ["map_shard"],
             "fan_out": {"over": "shards", "max": max_n, "on_partial": on_partial},
             "outputs": ["score"]},
        ],
        edges=[{"from": "split", "to": "work"}],
    )


def test_fan_out_runs_the_node_once_per_shard():
    """`parallel_group` was only ever a label: the node ran exactly once."""
    runner = _Shards({"shards": [1, 2, 3]})
    rep = run_graph(_fanned(), runner)
    assert runner.calls == 4  # split + 3 shards
    assert len(rep.frames_for("work")) == 3
    assert [f["shard"] for f in rep.frames_for("work")] == [0, 1, 2]


def test_fan_out_makes_downstream_values_lists():
    doc = _fanned()
    doc["nodes"].append({"id": "sum", "speciality": "reducer", "abilities": ["reduce_merge"]})
    doc["edges"].append({"from": "work", "to": "sum"})
    doc["verification"] = [{"assert": "score == [10, 20, 30]"}]
    rep = run_graph(doc, _Shards({"shards": [1, 2, 3]}))
    assert rep.passed, rep.assert_failures


def test_truncated_fan_out_says_what_it_dropped():
    """A truncated fan-out reporting full coverage is the quiet lie v1.2 refuses."""
    rep = run_graph(_fanned(max_n=2), _Shards({"shards": [1, 2, 3, 4, 5]}))
    assert len(rep.frames_for("work")) == 2
    assert rep.truncations, "silent truncation"
    assert "3 not processed" in rep.truncations[0]
    assert "fan_out.max=2" in rep.truncations[0]


def test_fan_out_over_a_missing_key_processes_nothing_rather_than_guessing():
    rep = run_graph(_fanned(), _Shards({}))
    assert rep.frames_for("work") == []


def test_on_partial_fail_marks_the_node_errored():
    class _Flaky(_Shards):
        def run(self, node, bb):
            if "shard" in bb:
                return {"error": "boom"} if bb["shard_index"] == 1 else {"ok": True}
            return {"shards": [1, 2, 3]}

    rep = run_graph(_fanned(on_partial="fail"), _Flaky())
    frame_out = [f["out"] for f in rep.frames if f["node"] == "work"]
    assert sum(1 for o in frame_out if o.get("error")) == 1


# --------------------------------------------------------------------- aggregate


@pytest.mark.parametrize(
    ("op", "values", "expected"),
    [
        ("majority", ["a", "b", "a"], "a"),
        ("majority", ["a", "b"], None),          # a tie is a signal, not noise
        ("median", [5, 1, 3], 3),
        ("union", [[1, 2], [2, 3]], [1, 2, 2, 3]),
        ("best", [4, 9, 2], 9),
    ],
)
def test_aggregate_reduces_before_the_node_runs(op, values, expected):
    doc = _g(
        nodes=[{"id": "seed", "speciality": "analyst", "abilities": ["analyze"],
                "outputs": ["votes"]},
               {"id": "decide", "speciality": "judge", "abilities": ["adjudicate"],
                "aggregate": {"op": op, "over": "votes"}}],
        edges=[{"from": "seed", "to": "decide"}],
    )
    seen = {}

    class _Capture:
        name = "mock"

        def run(self, node, bb):
            if node["id"] == "seed":
                return {"votes": values}
            seen["votes"] = bb["votes"]
            return {}

    run_graph(doc, _Capture())
    assert seen["votes"] == expected


# ------------------------------------------------------------------------ search


def _searching(objective="max", depth=2, branch=3):
    return _g(
        nodes=[{"id": "explore", "speciality": "producer", "abilities": ["generate"],
                "kind": "search",
                "search": {"branch": branch, "depth": depth, "score": "candidate",
                           "objective": objective, "prune": "beam(1)"}}],
        edges=[{"from": "explore", "to": "explore", "when": "never"}],
    )


class _Improving:
    """Each depth produces strictly better candidates — a measurable gradient."""

    name = "mock"

    def __init__(self):
        self.n = 0

    def run(self, node, bb):
        self.n += 1
        return {"candidate": bb.get("search_depth", 0) * 10 + bb.get("branch_index", 0)}


def test_search_explores_branch_times_depth_and_keeps_the_best():
    rep = run_graph(_searching(), _Improving())
    assert len(rep.frames_for("explore")) == 6  # branch 3 x depth 2, beam(1)
    assert rep.searches[0]["rounds"][0]["evaluated"] == 3


def test_search_measurably_improves_across_rounds():
    """B6: the criterion is a measured improvement, not the presence of branches."""
    rep = run_graph(_searching(), _Improving())
    rounds = rep.searches[0]["rounds"]
    assert rounds[-1]["best"] > rounds[0]["best"]
    assert rep.searches[0]["improved"] is True


def test_search_honours_a_minimising_objective():
    rep = run_graph(_searching(objective="min"), _Improving())
    rounds = rep.searches[0]["rounds"]
    assert rounds[0]["best"] == 0
    assert rep.searches[0]["improved"] is False  # nothing beats depth 0 when minimising


def test_unscoreable_candidates_are_dropped_not_crashed():
    class _Unscoreable:
        name = "mock"

        def run(self, node, bb):
            return {"something_else": 1}

    rep = run_graph(_searching(), _Unscoreable())
    assert rep.searches[0]["rounds"] == []


# ------------------------------------------- phase-scoped verification (v2's deferral)


def test_child_asserts_are_evaluated_against_their_phase_not_the_final_board():
    """B4. v1.1 dropped child verification precisely because this was impossible.

    The child asserts on `output.child_key`. A later phase overwrites `output`
    entirely, so the same assert fails against the final blackboard and passes
    against the phase frame. That difference is the whole feature.
    """
    doc = load(ROOT / "graphs/software-engineering/feature-delivery-lifecycle/graph.yaml")
    cases = {c["id"]: c for c in yaml.safe_load(
        (ROOT / "evals/feature-delivery-lifecycle/cases.yaml").read_text())["cases"]}
    rep = run_graph(doc, MockRunner(cases["clean-path-releases"]["node_outputs"]), root=ROOT)
    assert rep.passed, rep.assert_failures

    # the final board's `output` does NOT carry the child's keys...
    final = rep.frames[-1]["out"].get("output", {})
    assert "test_failed_before_patch" not in final
    # ...but the phase frame does, which is why the inherited assert holds
    assert rep.phase_frame("implement")["output"]["test_failed_before_patch"] is True


def test_phase_frame_accumulates_rather_than_taking_the_last_write():
    """A child ends with an accumulated board; only the last write loses keys."""
    doc = load(ROOT / "graphs/devops-sre/incident-lifecycle/graph.yaml")
    case = yaml.safe_load((ROOT / "evals/incident-lifecycle/cases.yaml").read_text())["cases"][0]
    rep = run_graph(doc, MockRunner(case["node_outputs"]), root=ROOT)
    frame = rep.phase_frame("postmortem")
    # `output` is written by postmortem.produce, but postmortem.review runs after it
    assert "output" in frame and "timeline" in frame["output"]
    assert rep.trace.index("postmortem.review") > rep.trace.index("postmortem.produce")


def test_expansion_tags_child_verification_with_its_phase():
    out = expand(load(ROOT / "graphs/software-engineering/feature-delivery-lifecycle/graph.yaml"), ROOT)
    assert {v["phase"] for v in out["verification"] if v.get("phase")} == {"implement", "test", "audit"}
    assert out["apiVersion"] == "agr/v1.2"


# ------------------------------------------------------------------------- replay


def test_replay_runner_grades_as_live_not_fixture(tmp_path):
    rec = {"model": "qwen2.5-coder:7b", "recorded": "2026-08-09",
           "node_outputs": {"a": {"x": 1}, "b": {"y": 2}}}
    path = tmp_path / "case.json"
    path.write_text(json.dumps(rec))
    runner = ReplayRunner.load(path)
    assert runner.name == "llm-replay:qwen2.5-coder:7b"

    from agenticgraphs.evalcmd import verification_depth
    doc = _g(verification=[{"assert": "y == 2"}])
    assert verification_depth(doc, runner.name) == "assert-live"
    assert verification_depth(doc, "mock") == "assert-fixture"


def test_a_recording_is_not_a_human_signature(tmp_path):
    from agenticgraphs.harness import HumanGateRequired

    path = tmp_path / "case.json"
    path.write_text(json.dumps({"model": "m", "node_outputs": {}}))
    runner = ReplayRunner.load(path)
    with pytest.raises(HumanGateRequired):
        runner.approve({"id": "gate", "approval": {"contract": "signed_off == true"}}, {})


# -------------------------------------------------------------------------- lints


def test_fan_out_over_an_unproduced_key_is_an_error():
    doc = _fanned()
    doc["nodes"][0]["outputs"] = []
    assert any("fans out over 'shards'" in e for e in lint_graph(doc))


def test_aggregate_over_an_unproduced_key_is_an_error():
    doc = _g(nodes=[{"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
                    {"id": "b", "speciality": "judge", "abilities": ["adjudicate"],
                     "aggregate": {"op": "majority", "over": "nope"}}])
    assert any("aggregates 'nope'" in e for e in lint_graph(doc))


def test_unparseable_search_score_is_an_error():
    doc = _searching()
    doc["nodes"][0]["search"]["score"] = "whichever one looks best"
    assert any("search score is not a parseable" in e for e in lint_graph(doc))


def test_search_node_without_a_search_block_is_rejected_by_schema():
    doc = _g(nodes=[{"id": "a", "speciality": "producer", "abilities": ["generate"],
                     "kind": "search"},
                    {"id": "b", "speciality": "producer", "abilities": ["generate"]}])
    assert validate_schema(doc, "graph")


def test_v12_feature_under_v11_apiversion_is_an_error():
    doc = _fanned()
    doc["apiVersion"] = "agr/v1.1"
    assert any("bump to 'agr/v1.2'" in e for e in lint_graph(doc))


def test_verification_phase_must_name_a_subgraph():
    doc = _g(verification=[{"phase": "nonexistent", "assert": "x == 1"}])
    assert any("is not a kind: subgraph node" in e for e in lint_graph(doc))


def test_whole_registry_still_validates_and_passes():
    bad = {p.parent.name: errs for p in iter_graphs() if (errs := validate_graph_file(p))}
    assert not bad, bad
    total = passed = 0
    for gp in iter_graphs():
        doc = load(gp)
        for case in yaml.safe_load(
                (ROOT / "evals" / doc["name"] / "cases.yaml").read_text())["cases"]:
            total += 1
            passed += run_graph(doc, MockRunner(case["node_outputs"]), root=ROOT).passed
    assert passed == total, f"{total - passed} of {total} failing"


# ------------------------------------------------- state schema and memory (B7, F3)


def test_state_schema_is_enforced_not_merely_declared():
    """v1.1 accepted `state.schema` and never read it, deferring 'until it has a consumer'."""
    doc = load(ROOT / "graphs/software-engineering/flaky-test-reflexion/graph.yaml")
    case = yaml.safe_load(
        (ROOT / "evals/flaky-test-reflexion/cases.yaml").read_text())["cases"][0]
    assert doc["state"]["schema"] == "state/lessons.schema.json"

    rep = run_graph(doc, MockRunner(case["node_outputs"]), root=ROOT)
    assert rep.passed and not rep.state_violations

    broken = json.loads(json.dumps(case["node_outputs"]))
    broken["evaluate"]["lessons"] = "not-a-list"
    rep = run_graph(doc, MockRunner(broken), root=ROOT)
    assert not rep.passed
    assert "is not of type 'array'" in rep.state_violations[0]


def test_a_missing_state_schema_is_reported_rather_than_ignored():
    doc = _g(state={"schema": "state/does-not-exist.json"})
    rep = run_graph(doc, MockRunner({}), root=ROOT)
    assert any("does not resolve" in v for v in rep.state_violations)


def test_reflexion_lessons_are_captured_on_the_report():
    """A reflexion graph that cannot carry a lesson is a retry loop with vocabulary."""
    doc = load(ROOT / "graphs/software-engineering/flaky-test-reflexion/graph.yaml")
    case = yaml.safe_load(
        (ROOT / "evals/flaky-test-reflexion/cases.yaml").read_text())["cases"][0]
    rep = run_graph(doc, MockRunner(case["node_outputs"]), root=ROOT)
    assert rep.lessons and all(isinstance(x, dict) for x in rep.lessons)


def test_graph_scoped_memory_appends_to_disk(tmp_path):
    (tmp_path / "graphs" / "software-engineering" / "m").mkdir(parents=True)
    doc = _g(name="m", memory={"scope": "graph"},
             nodes=[{"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
                    {"id": "b", "speciality": "evaluator", "abilities": ["evaluate"]}])
    run_graph(doc, MockRunner({"a": {}, "b": {"lessons": [{"tried": "x"}]}}), root=tmp_path)
    line = (tmp_path / "graphs/software-engineering/m/memory.jsonl").read_text().strip()
    assert json.loads(line)["lesson"] == {"tried": "x"}


def test_run_scoped_memory_does_not_touch_disk(tmp_path):
    (tmp_path / "graphs" / "software-engineering" / "m").mkdir(parents=True)
    doc = _g(name="m", memory={"scope": "run"},
             nodes=[{"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
                    {"id": "b", "speciality": "evaluator", "abilities": ["evaluate"]}])
    rep = run_graph(doc, MockRunner({"a": {}, "b": {"lessons": [{"tried": "x"}]}}), root=tmp_path)
    assert rep.lessons == [{"tried": "x"}]
    assert not (tmp_path / "graphs/software-engineering/m/memory.jsonl").exists()


def test_parallel_group_now_only_marks_distinct_siblings():
    """B3: the label must be true or absent — never a claim of parallelism that isn't."""
    label_only = []
    for gp in iter_graphs():
        doc = load(gp)
        groups: dict[str, list[str]] = {}
        for n in doc["nodes"]:
            if n.get("parallel_group"):
                groups.setdefault(n["parallel_group"], []).append(n["id"])
        for members in groups.values():
            # A group of one node was a fan-out claim; those are `fan_out` now.
            if len(members) < 2:
                label_only.append((doc["name"], members))
    assert not label_only, f"parallel_group still standing in for fan-out: {label_only}"


def test_fan_out_is_actually_used_by_the_migrated_graphs():
    fanned = [load(gp)["name"] for gp in iter_graphs()
              if any(n.get("fan_out") for n in load(gp)["nodes"])]
    assert len(fanned) >= 20, f"only {len(fanned)} graphs fan out"
