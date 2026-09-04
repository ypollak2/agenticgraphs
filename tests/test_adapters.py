import ast

import pytest

from agenticgraphs.adapters import emit_autogen, emit_crewai, emit_langgraph
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import iter_graphs, load
from agenticgraphs.subgraphs import expand, has_subgraphs


def test_every_graph_compiles_to_valid_langgraph_source():
    """Emitted source must cover the *executable* graph, not the authored one.

    A `kind: subgraph` phase stands for a child graph's whole topology, so after
    v1.1 the authored node list is not what runs. Asserting against the authored
    ids let the adapter drop every child silently.
    """
    from agenticgraphs.subgraphs import expand, has_subgraphs

    for g in iter_graphs():
        doc = load(g)
        src = emit_langgraph(doc)
        ast.parse(src)  # syntactically valid Python
        executable = expand(doc) if has_subgraphs(doc) else doc
        for n in executable["nodes"]:
            assert f'g.add_node("{n["id"]}"' in src, f"{doc['name']} dropped {n['id']}"
        assert "app = g.compile()" in src
        assert "NotImplementedError" in src  # honest: behavior must be bound


def test_router_emits_first_match_semantics():
    src = emit_langgraph(load(find_graph("cost-routed-research")))
    assert "hits[0] if hits else END" in src


@pytest.mark.parametrize("name", ["cost-routed-research", "verifier-swarm"])
def test_crewai_target_compiles(name):
    doc = load(find_graph(name))
    src = emit_crewai(doc)
    compile(src, f"<{name}-crewai>", "exec")  # runnable-shaped: no syntax errors
    assert "from crewai import Agent, Crew, Process, Task" in src
    for n in doc["nodes"]:
        assert f'role="{n["speciality"]}"' in src
        assert f"agent={n['id'].replace('-', '_')}" in src.replace("node_", "")
    assert "process=Process.sequential" in src
    assert doc.get("termination", {}).get("contract") in src


def test_crewai_terminal_task_gets_contract_as_expected_output():
    doc = load(find_graph("cost-routed-research"))
    src = emit_crewai(doc)
    has_out = {e["from"] for e in doc["edges"]}
    terminals = [n["id"] for n in doc["nodes"] if n["id"] not in has_out]
    assert terminals, "graph must have a terminal node for this assertion to be meaningful"
    for t in terminals:
        var = "node_" + t.replace("-", "_")
        idx = src.index(f"{var}_task = Task(")
        chunk = src[idx: idx + 400]
        assert doc["termination"]["contract"] in chunk


@pytest.mark.parametrize("name", ["cost-routed-research", "verifier-swarm"])
def test_autogen_target_compiles(name):
    doc = load(find_graph(name))
    src = emit_autogen(doc)
    compile(src, f"<{name}-autogen>", "exec")  # runnable-shaped: no syntax errors
    assert "from autogen import AssistantAgent, ConversableAgent, GroupChat, GroupChatManager" in src
    assert "def is_termination_msg(msg: dict) -> bool:" in src
    assert "def _select_speaker(last_speaker, groupchat):" in src
    for n in doc["nodes"]:
        assert f'name="{n["id"]}"' in src
    assert "GroupChatManager(groupchat=groupchat)" in src


def test_autogen_router_encodes_edge_conditions():
    doc = load(find_graph("cost-routed-research"))
    src = emit_autogen(doc)
    conditional = [e for e in doc["edges"] if e.get("when")]
    assert conditional, "expected at least one conditional edge on this router graph"
    for e in conditional:
        assert repr(e["when"]) in src


def test_mcp_tools_registered():
    pytest.importorskip("mcp")
    import asyncio

    from agenticgraphs.mcp_server import create_server

    tools = asyncio.run(create_server().list_tools())
    assert {t.name for t in tools} == {
        "search_graphs", "get_graph", "instantiate", "infuse_ability",
        # R6-01: what the CLI could do and the MCP surface could not
        "validate_graph", "run_graph", "list_abilities", "list_specialities", "get_profile",
        "diff_graphs",
    }


def test_compiled_topology_matches_executed_topology():
    """Parity: what `agr adapt` compiles is what `agr eval` runs.

    Nothing asserted this before, which is how a composite could compile to 10
    nodes while executing 17 — each subgraph phase became a single
    NotImplementedError stub and the child graph vanished from the build.
    """
    from agenticgraphs.harness import MockRunner, run_graph
    from agenticgraphs.subgraphs import expand, has_subgraphs

    for g in iter_graphs():
        doc = load(g)
        executable = expand(doc) if has_subgraphs(doc) else doc
        for emit in (emit_langgraph, emit_crewai, emit_autogen):
            src = emit(doc)
            for n in executable["nodes"]:
                assert n["id"] in src, f"{doc['name']}: {emit.__name__} dropped {n['id']}"
        # and every node the harness can reach is one the adapter emitted
        compiled = {n["id"] for n in executable["nodes"]}
        rep = run_graph(doc, MockRunner({}))
        assert set(rep.trace) <= compiled, doc["name"]


# --------------------------------------------------------------- runnable-ness
#
# `ast.parse` proves the emitter produced Python. It does not prove the emitted
# module builds a graph, and none of these frameworks were installed, so nothing
# ever imported one. An upstream rename in `langgraph.graph` would have kept
# every test green while `agr adapt` shipped source that cannot run.

langgraph = pytest.importorskip("langgraph.graph", reason="install the `adapters` extra")


@pytest.mark.parametrize("name", ["code-review-pipeline", "incident-triage-router",
                                  "verifier-swarm"])
def test_emitted_langgraph_module_actually_builds(name, tmp_path):
    """Execute the generated module and compile the StateGraph it declares.

    The node bodies raise NotImplementedError by design — structure is compiled,
    behavior is bound — so this asserts the graph *builds*, which is the part the
    adapter is responsible for.
    """
    src = emit_langgraph(load(find_graph(name)))
    ns: dict = {}
    exec(compile(src, f"<{name}>", "exec"), ns)
    app = ns["app"]
    assert app is not None
    graph = app.get_graph()
    doc = load(find_graph(name))
    executable = expand(doc) if has_subgraphs(doc) else doc
    emitted = set(graph.nodes) - {"__start__", "__end__"}
    assert emitted == {n["id"] for n in executable["nodes"]}


def test_emitted_langgraph_routes_the_same_branch_the_harness_does():
    """Adapter and harness must agree on a router, or the compiled app is a
    different graph from the one the eval profile describes."""
    doc = load(find_graph("incident-triage-router"))
    src = emit_langgraph(doc)
    ns: dict = {}
    exec(compile(src, "<router>", "exec"), ns)
    cond = ns["_cond"]
    assert cond("complexity <= moderate", {"complexity": "low"})
    assert not cond("complexity > moderate", {"complexity": "low"})
    assert cond("complexity > moderate", {"complexity": "high"})


def test_emitted_stub_carries_the_rubric_to_whoever_binds_it():
    """The stub is where behavior gets bound, so it is where criteria must land.

    Emitting only the speciality handed the implementer a role label and left the
    domain knowledge in a YAML file they were not reading.
    """
    doc = load(find_graph("code-review-pipeline"))
    verifier = next(n for n in doc["nodes"] if n.get("kind") == "verifier")
    if not verifier.get("criteria"):
        pytest.skip("graph not yet migrated to v1.8 criteria")
    for emit in (emit_langgraph, emit_crewai, emit_autogen):
        assert verifier["criteria"] in emit(doc)
