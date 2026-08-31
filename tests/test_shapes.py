"""Typed outputs, evidence binding, and the pilot graph — (b), (c), (a).

Six versions of findings reduce to one sentence: *the contract names things and
never types them*. `outputs: [examples]` said a node produces `examples`; it never
said `examples` is a list of records carrying an `exit_code`. So gpt-4o ran 20 real
commands, summarised them into English, and satisfied every declaration it was
given while failing the assert.
"""
from __future__ import annotations

import pytest

from agenticgraphs import shapes
from agenticgraphs.harness import MockRunner, run_graph
from agenticgraphs.registry import ROOT, iter_graphs, load
from agenticgraphs.validate import lint_graph


def _g(nodes, **kw):
    doc = {"apiVersion": "agr/v1.5", "name": "unit-test-graph",
           "description": "a graph used only by unit tests",
           "category": "software-engineering", "nodes": nodes,
           "edges": [{"from": nodes[0]["id"], "to": nodes[-1]["id"]}],
           "termination": {"max_steps": 8, "contract": "b after a"}}
    doc.update(kw)
    return doc


# ---------------------------------------------------------------- (b) the language


@pytest.mark.parametrize("expr", ["str", "int", "list", "list[int]",
                                  "{a:int}", "list[{exit_code:int, file:str}]",
                                  "list[{a:{b:int}}]"])
def test_well_formed_shapes_parse(expr):
    assert shapes.parse(expr)["kind"]


@pytest.mark.parametrize("expr", ["", "banana", "list[nope]", "{}", "{a}"])
def test_malformed_shapes_are_rejected(expr):
    with pytest.raises(shapes.ShapeError):
        shapes.parse(expr)


def test_outputs_stay_backwards_compatible():
    node = {"id": "n", "outputs": ["patch", {"examples": "list[{exit_code:int}]"}]}
    assert shapes.names(node) == ["patch", "examples"]
    assert shapes.declared(node)["patch"] is None
    assert shapes.declared(node)["examples"] == "list[{exit_code:int}]"


def test_prose_where_records_were_promised_is_a_violation():
    """The exact pilot failure, as a unit test."""
    node = {"id": "verify", "outputs": [{"examples": "list[{exit_code:int}]"}]}
    assert shapes.violations(node, {"examples": [{"exit_code": 0}]}) == []
    bad = shapes.violations(node, {"examples": ["all code snippets ran fine"]})
    assert bad and "expected an object" in bad[0]


def test_bool_does_not_satisfy_int():
    """`True` is an int in Python; an assert counting things does not want it."""
    node = {"id": "n", "outputs": [{"count": "int"}]}
    assert shapes.violations(node, {"count": True})


def test_a_fanned_out_node_is_checked_as_a_list_of_its_shape():
    """A shape describes ONE execution; v1.2 merges shards into a list."""
    node = {"id": "work", "fan_out": {"over": "tasks"},
            "outputs": [{"work_result": "{exit_code:int}"}]}
    assert shapes.violations(node, {"work_result": [{"exit_code": 0}]}) == []
    assert shapes.violations(node, {"work_result": {"exit_code": 0}})


def test_an_untyped_output_is_never_checked():
    node = {"id": "n", "outputs": ["anything"]}
    assert shapes.violations(node, {"anything": "prose is fine here"}) == []


def test_the_shape_reaches_the_prompt():
    node = {"id": "n", "outputs": [{"examples": "list[{exit_code:int}]"}]}
    text = shapes.describe(node)
    assert "list[{exit_code:int}]" in text
    assert "not prose descriptions" in text


def test_a_bad_shape_is_a_lint_error():
    doc = _g([{"id": "a", "speciality": "analyst", "abilities": ["analyze"],
               "outputs": [{"x": "banana"}]},
              {"id": "b", "speciality": "producer", "abilities": ["generate"]}])
    assert any("bad shape" in e for e in lint_graph(doc))


def test_a_shape_violation_fails_the_run():
    doc = _g([{"id": "a", "speciality": "analyst", "abilities": ["analyze"],
               "outputs": [{"n": "int"}]},
              {"id": "b", "speciality": "producer", "abilities": ["generate"]}])
    rep = run_graph(doc, MockRunner({"a": {"n": "seven"}, "b": {}}))
    assert not rep.passed
    assert "expected int" in rep.shape_violations[0]


# ------------------------------------------------- (c) evidence on the blackboard


def test_tool_results_land_on_the_blackboard_addressable_by_ability():
    """The gap: rep.tool_calls was built for auditing, and the assert reads what
    the model wrote. A node could make 20 perfect calls and still hand over prose.
    """
    from agenticgraphs.bindings import ToolCall

    class _Tooling:
        name = "tools:test"

        def __init__(self):
            self.report = None
            self.allow_mutating = True

        def run(self, node, bb):
            if node["id"] == "a" and self.report is not None:
                self.report.tool_calls.append(
                    ToolCall("run_command", {"command": "true"}, True, "ok",
                             {"exit_code": 0}))
            return {"seen": sorted(bb.get("tools", {}))}

    doc = _g([{"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
              {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
             verification=[{"assert": "all(c.exit_code == 0 for c in tools.run_command)"}])
    rep = run_graph(doc, _Tooling())
    assert rep.passed, rep.assert_failures
    assert rep.grounded


def test_a_failed_tool_call_is_not_bound_as_evidence():
    from agenticgraphs.bindings import ToolCall

    class _Failing:
        name = "tools:test"

        def __init__(self):
            self.report = None
            self.allow_mutating = True

        def run(self, node, bb):
            if self.report is not None:
                self.report.tool_calls.append(
                    ToolCall("run_command", {}, False, "refused"))
            return {"tools_seen": list(bb.get("tools", {}))}

    doc = _g([{"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
              {"id": "b", "speciality": "producer", "abilities": ["generate"]}])
    rep = run_graph(doc, _Failing())
    assert rep.frames[-1]["out"]["tools_seen"] == []


# ------------------------------------------------------------ (a) the pilot graph


def test_the_pilot_graph_types_the_key_its_assert_reads():
    doc = load(ROOT / "graphs/software-engineering/docs-code-sync-audit/graph.yaml")
    verify = next(n for n in doc["nodes"] if n["id"] == "verify")
    assert shapes.declared(verify)["examples"] == "list[{doc:str, exit_code:int}]"
    plan = next(n for n in doc["nodes"] if n["id"] == "plan")
    # A "task" was prose, so the fan-out iterated instructions and each shard
    # invented an example to have something to run.
    assert "doc" in shapes.declared(plan)["tasks"]


def test_no_registry_shape_is_malformed():
    bad = {load(gp)["name"]: [e for e in lint_graph(load(gp)) if "bad shape" in e]
           for gp in iter_graphs() if any("bad shape" in e for e in lint_graph(load(gp)))}
    assert not bad, bad


# ------------------------------------------------- the provenance-gap lint (T2)


def test_an_assert_demanding_provenance_with_no_bindable_ability_is_flagged():
    """`vendor-comparison-matrix` asked for `source_url` from nodes that could only
    `analyze` and `reduce_merge`. Nothing could search. That went undetected for
    nine versions because nothing ever asked.
    """
    from agenticgraphs.validate import provenance_gaps

    doc = _g([{"id": "a", "speciality": "analyst", "abilities": ["analyze"],
               "outputs": ["findings"]},
              {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
             verification=[{"assert": "all(f.source_url for f in output.findings)"}])
    gaps = provenance_gaps(doc)
    assert gaps and gaps[0][1] == ["source_url"]


def test_declaring_a_bindable_ability_closes_the_gap():
    from agenticgraphs.validate import provenance_gaps

    doc = _g([{"id": "a", "speciality": "researcher",
               "abilities": ["analyze", "web_search"], "outputs": ["findings"]},
              {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
             verification=[{"assert": "all(f.source_url for f in output.findings)"}])
    assert provenance_gaps(doc) == []


def test_the_gap_is_advisory_not_fatal():
    """A graph waiting for an integration must not be un-runnable."""
    from agenticgraphs.validate import lint_advisories, lint_graph

    doc = _g([{"id": "a", "speciality": "analyst", "abilities": ["analyze"],
               "outputs": ["findings"]},
              {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
             verification=[{"assert": "all(f.scanner_evidence for f in output.findings)"}])
    assert not [e for e in lint_graph(doc) if "provenance" in e]
    assert any("provenance" in w for w in lint_advisories(doc))


def test_asserted_keys_deep_reaches_record_fields():
    """`asserted_keys` returns blackboard keys; provenance lives one level in."""
    from agenticgraphs.validate import asserted_keys_deep

    got = asserted_keys_deep("all(e.get('log_id') or e.message_id for e in output.timeline)")
    assert {"log_id", "message_id", "timeline"} <= got


def test_a_speciality_never_loses_a_required_ability():
    """Minimality does not override what a role is defined to need — a pass to
    strip redundant grants removed `web_search` from a `researcher` node.
    """
    from agenticgraphs.registry import iter_yaml

    specs = {load(p)["name"]: load(p) for p in iter_yaml("specialities")}
    for gp in iter_graphs():
        for n in load(gp)["nodes"]:
            if n.get("kind") == "subgraph":
                continue
            required = set(specs.get(n["speciality"], {}).get("requires_abilities") or [])
            assert required <= set(n.get("abilities") or []), f"{gp.parent.name}/{n['id']}"
