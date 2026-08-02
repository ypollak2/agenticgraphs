import json

from agenticgraphs.cli import main
from agenticgraphs.inspect import find_graph, structural_profile, to_mermaid
from agenticgraphs.registry import iter_graphs, load


def test_mermaid_contains_every_node_and_edge():
    for g in iter_graphs():
        doc = load(g)
        m = to_mermaid(doc)
        assert m.startswith("flowchart LR")
        for n in doc["nodes"]:
            assert n["id"] in m
        assert m.count("-->") == len(doc["edges"])


def test_profile_risk_surface_and_bounds():
    doc = load(find_graph("verifier-swarm"))
    prof = structural_profile(doc)
    s = prof["structural"]
    assert s["risk_surface"] == "execute"
    assert s["loops_bounded"] is True
    assert s["verifier_nodes"] >= 1
    assert prof["measured"] is None  # honesty: no fake perf numbers pre-M1


def test_profiles_json_serializable_for_all_graphs():
    for g in iter_graphs():
        json.dumps(structural_profile(load(g)))


def test_cli_show_and_unknown(capsys):
    assert main(["show", "code-review-pipeline"]) == 0
    assert "code-review-pipeline" in capsys.readouterr().out
