"""A caller must be able to supply the subject, not just name it.

v1.9's finding was that a case seeding only a `goal` string starves the graph:
`alert-noise-reduction` was asked to deduplicate the last 30 days of paging
alerts and handed nothing to deduplicate, so its `map` node returned the literal
string `"map_shard"` — its own output key, as a placeholder. 71 of 83 graphs were
scored that way, averaging 0.614 against 0.898 for the twelve that seeded data.

The fix shipped as fixtures. It did not ship as an interface: `--goal` could
rename the subject but not supply it, and `run_graph` over MCP accepted an
`inputs` argument and silently ignored it, attaching a note telling the caller to
use `goal` instead. So the only way to run a graph over MCP was the starved path
the release existed to close (2026-09-12 audit, C9).
"""
from __future__ import annotations

import json

import pytest

from agenticgraphs.evalcmd import case_inputs


def test_inputs_overlay_onto_the_case():
    case = {"id": "c", "goal": "the last 30 days of paging alerts",
            "inputs": {"alerts": ["a", "b"], "window_days": 30}}
    seed = case_inputs(case, inputs={"alerts": ["x", "y", "z"]})
    assert seed["alerts"] == ["x", "y", "z"], "the supplied key wins"
    assert seed["window_days"] == 30, "keys not overridden survive"
    assert seed["goal"] == "the last 30 days of paging alerts"


def test_goal_still_wins_over_an_inputs_goal():
    """`--goal` is the more specific flag; it must not be shadowed."""
    case = {"id": "c", "goal": "from the case"}
    seed = case_inputs(case, goal="from the flag", inputs={"goal": "from inputs"})
    assert seed["goal"] == "from the flag"


def test_no_inputs_is_the_previous_behaviour_exactly():
    case = {"id": "c", "goal": "g", "inputs": {"k": 1}}
    assert case_inputs(case) == case_inputs(case, inputs=None) == {"goal": "g", "k": 1}


def test_empty_inputs_changes_nothing():
    case = {"id": "c", "goal": "g", "inputs": {"k": 1}}
    assert case_inputs(case, inputs={}) == {"goal": "g", "k": 1}


# ----------------------------------------------------------------------- CLI


def test_cli_reads_inputs_as_json():
    from agenticgraphs.cli import _read_inputs

    assert _read_inputs('{"alerts": [1, 2]}') == {"alerts": [1, 2]}
    assert _read_inputs(None) is None
    assert _read_inputs("") is None


def test_cli_reads_inputs_from_a_file(tmp_path):
    from agenticgraphs.cli import _read_inputs

    f = tmp_path / "subject.json"
    f.write_text(json.dumps({"invoices": [{"id": "INV-1"}]}))
    assert _read_inputs(f"@{f}") == {"invoices": [{"id": "INV-1"}]}


@pytest.mark.parametrize("bad", ["not json", "[1, 2]", '"a string"', "3"])
def test_cli_refuses_anything_but_an_object(bad):
    """A list or scalar would surface later as a confusing blackboard error."""
    from agenticgraphs.cli import _read_inputs

    with pytest.raises(SystemExit) as e:
        _read_inputs(bad)
    assert e.value.code == 2


# ----------------------------------------------------------------------- MCP


def test_mcp_run_graph_actually_uses_inputs(monkeypatch):
    """The regression that matters: the argument reaches `eval_graph`.

    It previously travelled as far as a `note` on the result and no further.
    """
    pytest.importorskip("mcp")
    from agenticgraphs import mcp_server

    seen = {}

    def fake_eval(name, **kw):
        seen.update(kw)
        return {"measured": {"runner": "mock", "pass_rate": 1.0}}

    import agenticgraphs.evalcmd as evalcmd

    monkeypatch.setattr(evalcmd, "eval_graph", fake_eval)
    server = mcp_server.create_server()
    tools = {n: t.fn for n, t in server._tool_manager._tools.items()}

    out = tools["run_graph"]("alert-noise-reduction", inputs={"alerts": [{"id": 1}]})
    assert seen["inputs"] == {"alerts": [{"id": 1}]}
    assert "note" not in out, "the parameter works; the apology for it should be gone"


def test_mcp_run_graph_refuses_a_non_object(monkeypatch):
    pytest.importorskip("mcp")
    from agenticgraphs import mcp_server

    server = mcp_server.create_server()
    tools = {n: t.fn for n, t in server._tool_manager._tools.items()}
    with pytest.raises(ValueError, match="must be an object"):
        tools["run_graph"]("alert-noise-reduction", inputs=["not", "an", "object"])


# ------------------------------------------------- an override must not persist


def test_an_override_run_does_not_overwrite_the_profile():
    """A profile is a claim about the graph's fixtures, not about an ad-hoc run.

    `agr goal` has passed a goal override since v1.7 with `write` at its default,
    so every exploratory run quietly rewrote the graph's checked-in evidence.
    `--inputs` would have widened that from one string to the whole blackboard.
    """
    import subprocess

    from agenticgraphs.evalcmd import eval_graph
    from agenticgraphs.registry import ROOT

    def dirty() -> str:
        return subprocess.run(
            ["git", "status", "--porcelain", "--", "graphs/*/*/profile.json"],
            cwd=ROOT, capture_output=True, text=True, timeout=30).stdout

    assert dirty() == "", "this test needs a clean evidence store to start from"

    eval_graph("alert-noise-reduction", replay=False,
               inputs={"alerts": [{"id": "A1"}, {"id": "A2"}]})
    assert dirty() == "", "an --inputs run persisted a profile"

    eval_graph("alert-noise-reduction", replay=False, goal="something else entirely")
    assert dirty() == "", "a --goal run persisted a profile"


def test_an_unsteered_run_still_writes(monkeypatch):
    """The default must not have become write=False for ordinary runs."""
    from agenticgraphs import evalcmd

    wrote = []
    monkeypatch.setattr(evalcmd, "write_profile", lambda gp, prof: wrote.append(gp))
    evalcmd.eval_graph("alert-noise-reduction", replay=False)
    assert wrote, "an ordinary eval must still persist its profile"


def test_write_true_forces_a_persist_even_under_an_override(monkeypatch):
    from agenticgraphs import evalcmd

    wrote = []
    monkeypatch.setattr(evalcmd, "write_profile", lambda gp, prof: wrote.append(gp))
    evalcmd.eval_graph("alert-noise-reduction", replay=False, goal="x", write=True)
    assert wrote
