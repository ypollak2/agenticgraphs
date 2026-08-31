"""Every graph declares a motif, and nothing ever checked it.

`usecase.yaml` names the pattern each graph implements, and the README organises
the whole registry around "the nineteen motifs". Ten graphs called themselves
`parallel-swarm` while being a linear three-node chain, and four still did after
the v1.8 topology work — including two `map-reduce` graphs that mapped over
nothing. A motif nothing verifies is the same defect as a contract nothing
verifies: a claim living inside the artifact.

Each rule pins the structure the motif is *about*. Getting that wrong is easy in
the obvious direction: a first pass judged `debate` by fan-out and flagged
`ab-test-analysis`, whose two advocates both feed one judge — a debate is
in-degree at the adjudicator, not out-degree at the source.
"""
from __future__ import annotations

import pytest
import yaml

from agenticgraphs.registry import iter_graphs, load
from agenticgraphs.validate import _lint_motif


def _doc(gpath):
    doc = load(gpath)
    doc["__pattern__"] = yaml.safe_load((gpath.parent / "usecase.yaml").read_text())["pattern"]
    return doc


def test_every_graph_implements_the_motif_it_declares():
    for gpath in iter_graphs():
        doc = _doc(gpath)
        assert _lint_motif(doc) == [], f"{doc['name']} ({doc['__pattern__']})"


def test_the_catalog_and_the_bundle_agree_on_the_motif():
    """Two places name the pattern; a lint reading one while the README reads the
    other would check nothing."""
    from agenticgraphs.registry import ROOT
    catalog = {e["name"]: e["pattern"]
               for e in load(ROOT / "usecases" / "catalog.yaml")["entries"]}
    for gpath in iter_graphs():
        doc = _doc(gpath)
        assert catalog[doc["name"]] == doc["__pattern__"]


@pytest.mark.parametrize("pattern,nodes,edges", [
    ("parallel-swarm",
     [{"id": "p"}, {"id": "w"}, {"id": "v"}],
     [{"from": "p", "to": "w"}, {"from": "w", "to": "v"}]),
    ("map-reduce",
     [{"id": "a"}, {"id": "b"}], [{"from": "a", "to": "b"}]),
    ("router", [{"id": "a"}, {"id": "b"}], [{"from": "a", "to": "b"}]),
    ("saga", [{"id": "a"}, {"id": "b"}], [{"from": "a", "to": "b"}]),
    ("human-gate", [{"id": "a"}, {"id": "b"}], [{"from": "a", "to": "b"}]),
    ("loop", [{"id": "a"}, {"id": "b"}], [{"from": "a", "to": "b"}]),
])
def test_a_label_on_a_linear_chain_is_refused(pattern, nodes, edges):
    doc = {"apiVersion": "agr/v1.8", "__pattern__": pattern,
           "nodes": nodes, "edges": edges}
    assert _lint_motif(doc), f"'{pattern}' accepted a chain that does not implement it"


def test_a_debate_is_judged_by_in_degree_not_fan_out():
    """Two advocates feeding one judge IS a debate. Judging it by out-degree
    flags every correct debate in the registry."""
    doc = {"apiVersion": "agr/v1.8", "__pattern__": "debate",
           "nodes": [{"id": "a"}, {"id": "b"}, {"id": "judge"}],
           "edges": [{"from": "a", "to": "judge"}, {"from": "b", "to": "judge"}]}
    assert _lint_motif(doc) == []


def test_a_router_need_not_be_kind_router():
    """A node with two mutually exclusive conditional out-edges routes, whatever
    its `kind` says — `invoice-reconciliation` routes from a subgraph node, which
    cannot carry `kind: router`."""
    doc = {"apiVersion": "agr/v1.8", "__pattern__": "router",
           "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
           "edges": [{"from": "a", "to": "b", "when": "x"},
                     {"from": "a", "to": "c", "when": "not x"}]}
    assert _lint_motif(doc) == []


def test_fan_out_satisfies_a_swarm_without_a_parallel_group():
    """Running one node over many shards is a swarm; a group of sibling nodes is
    the other way to express it, and both count."""
    doc = {"apiVersion": "agr/v1.8", "__pattern__": "parallel-swarm",
           "nodes": [{"id": "p"}, {"id": "w", "fan_out": {"over": "tasks"}}],
           "edges": [{"from": "p", "to": "w"}]}
    assert _lint_motif(doc) == []


def test_the_rule_is_armed_at_v1_8_only():
    """A rule written after a spec version must not retroactively fail it."""
    doc = {"apiVersion": "agr/v1.7", "__pattern__": "parallel-swarm",
           "nodes": [{"id": "a"}], "edges": []}
    assert _lint_motif(doc) == []
