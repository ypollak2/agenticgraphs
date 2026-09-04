from agenticgraphs.registry import iter_graphs, load
from agenticgraphs.validate import validate_graph_file


def test_every_graph_is_valid_and_the_readme_badge_counts_them():
    """Cross-artifact: the README badge must equal the registry. The old `>= 50`
    bound could not catch a badge that said 52 while 83 shipped (D8-06)."""
    import re

    from agenticgraphs.registry import ROOT

    graphs = iter_graphs()
    for g in graphs:
        assert validate_graph_file(g) == [], f"{g} failed"
    badge = re.search(r"badge/graphs-(\d+)-", (ROOT / "README.md").read_text())
    assert badge and int(badge.group(1)) == len(graphs)


def test_top50_covers_all_domains():
    domains = {load(g)["category"] for g in iter_graphs()}
    assert len(domains) == 15, sorted(domains)
