from agenticgraphs.registry import iter_graphs, load
from agenticgraphs.validate import validate_graph_file


def test_at_least_50_graphs_all_valid():
    graphs = iter_graphs()
    assert len(graphs) >= 50, f"only {len(graphs)} graphs"
    for g in graphs:
        assert validate_graph_file(g) == [], f"{g} failed"


def test_top50_covers_all_domains():
    domains = {load(g)["category"] for g in iter_graphs()}
    assert len(domains) == 15, sorted(domains)
