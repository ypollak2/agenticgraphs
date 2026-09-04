"""Real registry graphs' declared abilities flow into bind_for/invoke (R3-07).

`test_tool_grounding.py` and `test_runner_transport.py` hand-build minimal
nodes, so the registry's real `abilities:` lists and the binding layer could
drift without a test noticing (2026-09-04 audit, D8-05). Three shipped graphs
are exercised here end to end, with the subprocess stubbed so nothing runs.
"""
from __future__ import annotations

import subprocess

import pytest

from agenticgraphs import bindings
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import ROOT, load

#: graph -> node -> ability that must be bindable under allow_mutating
CASES = [
    ("verifier-swarm", "verifier", "run_command"),
    ("code-review-pipeline", "triage", "read_diff"),
    ("cost-routed-research", None, "web_search"),
]


@pytest.mark.parametrize("graph, node_id, ability", CASES)
def test_a_shipped_graphs_declared_ability_binds_and_invokes(graph, node_id, ability, monkeypatch):
    doc = load(find_graph(graph))
    nodes = [n for n in doc["nodes"] if ability in (n.get("abilities") or [])]
    assert nodes, f"{graph} declares no node with {ability}"
    node = next(n for n in nodes if node_id is None or n["id"] == node_id)

    bound = bindings.bind_for(node, allow_mutating=True)
    assert ability in bound and callable(bound[ability]["fn"])
    # The tool definition the model sees is derived from the same binding.
    tools = bindings.as_openai_tools(bound)
    assert ability in {t["function"]["name"] for t in tools}

    class _Proc:
        returncode, stdout, stderr = 0, "+++ b/x.py\n@@ -1,0 +2,1 @@\n", ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Proc())
    monkeypatch.setattr(bindings, "_web_search", lambda args, cwd, rep: {"results": []})
    monkeypatch.setitem(bindings.BUILTINS, "web_search", bindings._web_search)
    args = {"run_command": {"command": "true"}, "read_diff": {"ref": "HEAD"},
            "web_search": {"query": "x"}}[ability]
    call = bindings.invoke(ability, args, ROOT, allow_mutating=True)
    assert call.ok, call.detail
    assert call.ability == ability and isinstance(call.evidence, dict)


def test_a_declared_ability_with_no_binding_is_refused_not_faked():
    doc = load(find_graph("bug-triage-and-fix"))
    execute = next(n for n in doc["nodes"] if "execute_step" in n["abilities"])
    assert "execute_step" not in bindings.bind_for(execute, allow_mutating=True)
    assert execute.get("unbound_ok", "").startswith("narrated:"), "R3-04 declaration missing"
    call = bindings.invoke("execute_step", {}, ROOT, allow_mutating=True)
    assert not call.ok and "not bound" in call.detail


def test_mutating_risk_stays_unbound_without_the_opt_in():
    doc = load(find_graph("verifier-swarm"))
    verifier = next(n for n in doc["nodes"] if n["id"] == "verifier")
    assert "run_command" not in bindings.bind_for(verifier)
    assert "run_command" in bindings.bind_for(verifier, allow_mutating=True)
