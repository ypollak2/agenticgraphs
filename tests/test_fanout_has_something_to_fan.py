"""A fan_out must have something to fan over.

Six composites declared `fan_out: {over: shards}` (or `tasks`), had the producing
partition/plan node declare that key as an output, and shipped a golden fixture
that produced `shard_count: 1` or `steps: [decompose goal]` instead. The key was
never on the blackboard, so the fan had an empty list to iterate.

The mock harness ran the map node once anyway and the case passed at 100%. The
emitted LangGraph, correctly, produced zero `Send`s and went straight to END —
which is how this was found: the adapter round-trip (2026-09-12 audit, C12) put
the two runtimes side by side and they disagreed, with the harness being the
lenient one.

It is v1.9's finding one level down. v1.9 fixed cases that named a subject and
supplied none; this is a node that declares an output and produces something
else, with a fan-out downstream depending on the difference.
"""
from __future__ import annotations

import pytest
import yaml

from agenticgraphs.harness import MockRunner, run_graph
from agenticgraphs.registry import ROOT, iter_graphs, load
from agenticgraphs.subgraphs import expand, has_subgraphs


def _graphs_with_fanout():
    for gp in iter_graphs():
        doc = load(gp)
        executable = expand(doc, ROOT) if has_subgraphs(doc) else doc
        overs = {n["fan_out"]["over"] for n in executable["nodes"]
                 if (n.get("fan_out") or {}).get("over")}
        if overs and (gp.parent / "cases.yaml").exists():
            yield doc["name"], doc, executable, overs, gp.parent / "cases.yaml"


PARAMS = [(name, doc, ex, overs, cf) for name, doc, ex, overs, cf in _graphs_with_fanout()]


@pytest.mark.parametrize(("name", "doc", "executable", "overs", "cases_file"),
                         PARAMS, ids=[p[0] for p in PARAMS])
def test_every_case_puts_something_on_the_key_its_fan_out_iterates(
        name, doc, executable, overs, cases_file):
    gated = any(n.get("kind") == "human" for n in executable["nodes"])
    for case in yaml.safe_load(cases_file.read_text())["cases"]:
        seed = dict(case.get("inputs") or {})
        if case.get("goal"):
            seed["goal"] = case["goal"]
        rep = run_graph(doc, MockRunner(case["node_outputs"]), root=ROOT,
                        auto_approve=gated, inputs=seed)
        produced = set(seed)
        for frame in rep.frames:
            produced |= set((frame["out"] or {}).keys())
        missing = sorted(k for k in overs if k not in produced)
        assert not missing, (
            f"{name} / {case['id']}: fans out over {missing}, which nothing in the "
            f"run produced. The map node runs once on an empty list and the case "
            f"still passes; an exported graph sends zero shards and halts."
        )
