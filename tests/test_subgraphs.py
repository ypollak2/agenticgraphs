"""`subgraphs.py` had no test file of its own; its three `SubgraphError` branches
were uncovered (2026-09-04 audit, D8-04 / R3-09)."""
from __future__ import annotations

import pytest
import yaml

from agenticgraphs.registry import SPEC_VERSION
from agenticgraphs.subgraphs import MAX_DEPTH, SubgraphError, entry_nodes, expand, has_subgraphs


def _graph(name, nodes, edges, cat="cat"):
    return {"apiVersion": SPEC_VERSION, "name": name, "category": cat, "description": "fixture",
            "nodes": nodes, "edges": edges,
            "termination": {"max_steps": 5, "contract": "fixture"},
            "verification": [{"assert": "true"}]}


def _write(root, cat, name, doc):
    d = root / "graphs" / cat / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "graph.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


def _leaf(name):
    return _graph(name, [{"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
                         {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
                  [{"from": "a", "to": "b"}])


def _ref(name, ref):
    return _graph(name, [{"id": "phase", "speciality": "supervisor", "kind": "subgraph", "ref": ref}], [])


def test_a_graph_without_subgraphs_expands_to_itself(tmp_path):
    doc = _leaf("leaf")
    assert expand(doc, tmp_path) is doc
    assert not has_subgraphs(doc)


def test_expansion_prefixes_child_ids_and_wires_entry_and_terminal(tmp_path):
    _write(tmp_path, "cat", "leaf", _leaf("leaf"))
    parent = _graph("p", [{"id": "first", "speciality": "analyst", "abilities": ["analyze"]},
                          {"id": "phase", "speciality": "supervisor", "kind": "subgraph", "ref": "cat/leaf"}],
                    [{"from": "first", "to": "phase"}])
    out = expand(parent, tmp_path)
    ids = [n["id"] for n in out["nodes"]]
    assert ids == ["first", "phase.a", "phase.b"]
    assert {"from": "first", "to": "phase.a"} in [{"from": e["from"], "to": e["to"]} for e in out["edges"]]


def test_a_missing_ref_is_a_subgraph_error(tmp_path):
    with pytest.raises(SubgraphError, match="does not resolve"):
        expand(_ref("p", "cat/nope"), tmp_path)


def test_a_cycle_between_refs_is_named_in_the_error(tmp_path):
    _write(tmp_path, "cat", "a", _ref("a", "cat/b"))
    _write(tmp_path, "cat", "b", _ref("b", "cat/a"))
    with pytest.raises(SubgraphError, match="subgraph cycle: cat/b -> cat/a -> cat/b"):
        expand(_ref("a", "cat/b"), tmp_path)


def test_nesting_past_max_depth_is_refused(tmp_path):
    prev = "leaf"
    _write(tmp_path, "cat", prev, _leaf(prev))
    for i in range(MAX_DEPTH + 1):
        name = f"l{i}"
        _write(tmp_path, "cat", name, _ref(name, f"cat/{prev}"))
        prev = name
    with pytest.raises(SubgraphError, match="MAX_DEPTH"):
        expand(_ref("top", f"cat/{prev}"), tmp_path)


def test_a_child_with_no_entry_or_terminal_cannot_be_spliced(tmp_path):
    """With forward-only edges the first node is always an entry and the last
    always a terminal, so the only child that has neither is one with no nodes.
    `expand` guards it anyway, because a ref may point at anything on disk."""
    ring = _graph("ring", [{"id": "a", "speciality": "analyst", "abilities": ["analyze"]},
                           {"id": "b", "speciality": "producer", "abilities": ["generate"]}],
                  [{"from": "a", "to": "b"}, {"from": "b", "to": "a", "when": "true"}])
    assert entry_nodes(ring) == ["a"]  # a back-edge never disqualifies the start
    _write(tmp_path, "cat", "empty", _graph("empty", [], []))
    with pytest.raises(SubgraphError, match="no entry or no terminal"):
        expand(_ref("p", "cat/empty"), tmp_path)
