import copy

from agenticgraphs.registry import iter_graphs, iter_yaml, load
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
    # Pinned, not `iter_graphs()[0]`: the alphabetically-first graph is now a
    # composite whose first node is a `kind: subgraph` phase, and a subgraph node
    # legitimately declares no abilities (they live in the child graph).
    doc = load(next(g for g in iter_graphs() if "code-review-pipeline" in str(g)))
    bad = copy.deepcopy(doc)
    bad["nodes"][0]["abilities"] = []
    assert any("missing required abilities" in e for e in lint_graph(bad))


def test_schema_title_names_the_newest_api_version():
    """The schema's own title lagged one version behind its enum (2026-09-04 audit, D1-06)."""
    import json
    from pathlib import Path
    doc = json.loads((Path(__file__).parents[1] / "spec" / "agr-graph.schema.json").read_text())
    newest = sorted(doc["properties"]["apiVersion"]["enum"], key=lambda v: [int(x) for x in v.split("/v")[1].split(".")])[-1]
    assert doc["title"].endswith(newest.split("/")[1]), (doc["title"], newest)


def test_an_ability_outside_a_specialitys_declared_boundary_is_refused():
    """`optional_abilities` was set in 12 speciality files and read by no code
    (2026-09-04 audit, D2-03). Now a speciality that draws a boundary has it
    enforced: `migrator` allows execute_step/rollback/shadow_write/backfill."""
    doc = load(next(g for g in iter_graphs() if "schema-migration-saga" in str(g)))
    bad = copy.deepcopy(doc)
    node = next(n for n in bad["nodes"] if n["speciality"] == "migrator")
    node["abilities"].append("web_search")
    errs = [e for e in lint_graph(bad) if "allows only" in e]
    assert errs and "web_search" in errs[0] and "migrator" in errs[0]
    assert not [e for e in lint_graph(doc) if "allows only" in e]


def test_a_speciality_without_optional_abilities_draws_no_boundary():
    doc = load(next(g for g in iter_graphs() if "code-review-pipeline" in str(g)))
    bad = copy.deepcopy(doc)
    bad["nodes"][0]["abilities"].append("web_search")  # code-triage declares no optional list
    assert not [e for e in lint_graph(bad) if "allows only" in e]
