"""The CLI, which is the surface every documented command in the README uses.

At 55% most branches here were unexecuted, including the `validate` loop where
mypy later found a variable shadowed between an `except` name and a `for` target.
"""
from __future__ import annotations

import json

import pytest

from agenticgraphs.cli import main


def run(capsys, *argv) -> tuple[int, str]:
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_list_names_every_graph(capsys):
    """Exact, cross-surface: the CLI lists what the registry holds, no more, no
    less. A `>= 83` lower bound let the count drift in either direction (D8-06)."""
    from agenticgraphs.registry import iter_graphs

    code, out = run(capsys, "list")
    assert code == 0
    assert len([ln for ln in out.splitlines() if ln.strip()]) == len(iter_graphs())


def test_list_json_carries_the_derived_tier(capsys):
    code, out = run(capsys, "list", "--json")
    rows = [json.loads(ln) for ln in out.splitlines() if ln.strip()]
    assert code == 0 and {r["tier"] for r in rows} == {"primitive", "composite"}
    fdl = next(r for r in rows if r["name"] == "feature-delivery-lifecycle")
    assert fdl["tier"] == "composite"


def test_show_emits_the_definition(capsys):
    code, out = run(capsys, "show", "code-review-pipeline")
    assert code == 0 and "apiVersion" in out


def test_show_unknown_graph_is_an_error(capsys):
    with pytest.raises(SystemExit):
        run(capsys, "show", "no-such-graph")


def test_profile_reports_structural_facts(capsys):
    code, out = run(capsys, "profile", "code-review-pipeline")
    assert code == 0
    assert json.loads(out)["structural"]["nodes"] > 0


def test_mermaid_renders_a_diagram(capsys):
    code, out = run(capsys, "mermaid", "incident-triage-router")
    assert code == 0 and "flowchart" in out


def test_validate_passes_over_the_whole_registry(capsys):
    code, out = run(capsys, "validate")
    assert code == 0
    assert "FAIL" not in out


def test_adapt_compiles_each_supported_target(capsys):
    for target, marker in [("langgraph", "StateGraph"), ("crewai", "from crewai import"),
                           ("autogen", "autogen")]:
        code, out = run(capsys, "adapt", "code-review-pipeline", "--target", target)
        assert code == 0 and marker in out


def test_search_matches_on_description(capsys):
    code, out = run(capsys, "search", "incident")
    assert code == 0 and "incident" in out.lower()


def test_no_command_is_a_usage_error():
    """argparse exits 2 on a missing subcommand; that is the contract, not a bug."""
    with pytest.raises(SystemExit) as e:
        main([])
    assert e.value.code != 0


def test_mcp_without_the_extra_says_how_to_install_it(capsys, monkeypatch):
    """A bare `uv sync` has no `mcp` package; the command must say so instead of
    tracebacking (2026-09-04 audit, D9-7)."""
    import builtins
    real_import = builtins.__import__

    def no_mcp(name, *a, **kw):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("No module named 'mcp'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_mcp)
    monkeypatch.delitem(__import__("sys").modules, "agenticgraphs.mcp_server", raising=False)
    code = main(["mcp"])
    err = capsys.readouterr().err
    assert code == 2
    assert "uv sync --all-extras" in err
