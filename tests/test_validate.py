import copy

from agenticgraphs.registry import ROOT, iter_graphs, iter_yaml, load
from agenticgraphs.validate import lint_graph, validate_graph_file, validate_schema


def test_all_seed_graphs_valid():
    graphs = iter_graphs()
    assert len(graphs) >= 3
    for g in graphs:
        assert validate_graph_file(g) == [], f"{g} failed validation"


def test_all_specialities_and_abilities_valid():
    for kind, dirname in (("speciality", "specialities"), ("ability", "abilities")):
        files = iter_yaml(dirname)
        assert files, f"no {dirname} found"
        for f in files:
            assert validate_schema(load(f), kind) == [], f"{f} invalid"


def test_lint_catches_dangling_edge():
    doc = load(iter_graphs()[0])
    bad = copy.deepcopy(doc)
    bad["edges"].append({"from": "triage", "to": "ghost-node"})
    assert any("unknown node" in e for e in lint_graph(bad))


def test_lint_catches_unconditional_back_edge():
    doc = load(next(g for g in iter_graphs() if "verifier-swarm" in str(g)))
    bad = copy.deepcopy(doc)
    for e in bad["edges"]:
        e.pop("when", None)
    assert any("back-edge" in e for e in lint_graph(bad))


def test_lint_catches_missing_required_ability():
    doc = load(iter_graphs()[0])
    bad = copy.deepcopy(doc)
    bad["nodes"][0]["abilities"] = []
    assert any("missing required abilities" in e for e in lint_graph(bad))
