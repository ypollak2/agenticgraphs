"""M3 adapter: compile an AGR graph into runnable framework source.

Code generation, not a runtime dependency: the emitted module is self-contained
(embeds the condition evaluator), wires the full topology into a StateGraph, and
leaves each node as a NotImplementedError stub declaring the speciality/abilities
the implementer (human or agent) must bind. Structure is compiled; behavior is bound.
"""
from __future__ import annotations

from .subgraphs import expand, has_subgraphs


def _executable(doc: dict) -> dict:
    """The graph the harness actually runs.

    A `kind: subgraph` phase has no behaviour of its own — it stands for the
    child graph's whole topology. Compiling the unexpanded doc emitted one
    `NotImplementedError` stub per phase and silently dropped the child, so the
    generated module implemented a different graph from the one `agr eval` runs.
    Every emitter expands first.
    """
    return expand(doc) if has_subgraphs(doc) else doc


def _criteria(n: dict) -> str:
    """A node's rubric, escaped for embedding in a generated double-quoted string.

    Every emitter carries it. The stub (or the CrewAI goal, or the AutoGen system
    message) is where a human or an agent binds behavior, so it is exactly where
    the domain knowledge has to arrive — leaving it in a YAML file the implementer
    is not reading is how a "healthcare graph" ends up containing no healthcare.
    """
    return (n.get("criteria") or "").replace("\\", "\\\\").replace('"', '\\"')


def _fn(node_id: str) -> str:
    # Expanded subgraph ids carry a dot (`implement.plan`); both it and the
    # dash are illegal in a Python identifier.
    return "node_" + node_id.replace("-", "_").replace(".", "_")


#: The emitted module is self-contained by design, so the allowlist that
#: `agenticgraphs.safeexpr` applies at eval time is inlined here rather than
#: imported. Without it, every generated LangGraph/CrewAI/AutoGen app shipped
#: the escape `{"__builtins__": {}}` never closed.
_EMITTED_GUARD = '''\
import ast as _ast

_ALLOWED_NODES = {
    "Expression", "BoolOp", "And", "Or", "UnaryOp", "Not", "IfExp", "Compare",
    "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "Is", "IsNot", "In", "NotIn",
    "BinOp", "Add", "Sub", "Mult", "Div", "Mod", "Name", "Load", "Attribute",
    "Constant", "Subscript", "Slice", "List", "Tuple", "Set", "Dict", "Call",
    "GeneratorExp", "ListComp", "SetComp", "comprehension", "Store",
}
_CALLABLE_NAMES = {"len", "all", "any", "sum", "min", "max", "abs", "round"}


def _safe_expr(expr: str):
    """Compile `expr` only if every node is allowlisted. Returns None otherwise."""
    try:
        tree = _ast.parse(expr, mode="eval")
    except SyntaxError:
        return None
    for node in _ast.walk(tree):
        if type(node).__name__ not in _ALLOWED_NODES:
            return None
        if isinstance(node, _ast.Attribute) and node.attr.startswith("_"):
            return None
        if isinstance(node, _ast.Name) and node.id.startswith("_"):
            return None
        if isinstance(node, _ast.Call):
            fn = node.func
            if isinstance(fn, _ast.Attribute):
                if fn.attr != "get":
                    return None
            elif isinstance(fn, _ast.Name):
                if fn.id not in _CALLABLE_NAMES:
                    return None
            else:
                return None
    return compile(tree, "<agr-expr>", "eval")
'''

#: Contract checking, retries and the `output.` view, shared by every emitter
#: that can execute state. Emitted alongside the guard so the generated module
#: carries the graph's verification instead of only a prose docstring
#: (2026-09-04 audit, D5-01 / D5-03).
_CONTRACT_BLOCK = '''\


def _wrap(v):
    if isinstance(v, dict):
        return _View(v)
    if isinstance(v, list):
        return [_wrap(x) for x in v]
    return v


class _View:
    """`output.x` in an assert reads blackboard key `x`, and `f.file` reads a record
    field — the harness's OutputView semantics, so an assert means the same thing
    in generated code as in `agr eval`."""
    def __init__(self, s): self._s = s
    def __getattr__(self, k): return _wrap(self._s.get(k))
    def __getitem__(self, k): return _wrap(self._s[k])
    def __contains__(self, k): return k in self._s
    def __iter__(self): return iter(self._s)
    def __len__(self): return len(self._s)
    def __bool__(self): return bool(self._s)
    def __eq__(self, o): return self._s == (o._s if isinstance(o, _View) else o)
    def __hash__(self): return id(self)


def check_contract(state: dict) -> list:
    """Evaluate every `verification[].assert` against `state`; return the failures.

    Phase-scoped asserts (from subgraph children) are evaluated against the
    final state here, which the reference runtime scopes per phase; treat a
    phase-tagged failure as advisory. `CONTRACT_COMMANDS` are the checks that
    must run outside the model (a shell command, exit code is the fact); they
    are listed, not executed, by generated code.
    """
    failures = []
    for describe, expr, phase in CONTRACT:
        if not _cond(expr, {**{k: _wrap(v) for k, v in state.items()}, "output": _View(state)}):
            failures.append((f"[{phase}] " if phase else "") + (describe or expr))
    return failures


def _checked(fn):
    """Wrap a terminal node so the contract is checked when flow leaves it."""
    def run(state: dict) -> dict:
        out = fn(state) or {}
        failures = check_contract({**state, **out})
        return {**out, "contract_failures": failures,
                "failure_kinds": (["assert"] if failures else [])}
    run.__name__, run.__doc__ = fn.__name__, fn.__doc__
    return run


def _with_retries(fn, max_attempts: int, reissue_effects: bool):
    """Re-run a node whose output carries `error`, up to `retries.max` times.

    `reissue_effects` is the node's own declaration that a re-run may repeat a
    non-idempotent effect; it is carried here so the implementer sees it.
    """
    def run(state: dict) -> dict:
        out = fn(state) or {}
        attempts = 0
        while out.get("error") and attempts < max_attempts:
            attempts += 1
            out = fn({**state, "attempts": attempts}) or {}
        return {**out, "attempts": attempts}
    run.__name__, run.__doc__ = fn.__name__, fn.__doc__
    run.reissue_effects = reissue_effects
    return run
'''

_PRELUDE = _EMITTED_GUARD + '''\
from langgraph.graph import END, START, StateGraph

_ORDER = {"trivial": -1, "low": 0, "simple": 0, "medium": 1, "moderate": 1,
          "high": 2, "complex": 2, "critical": 3}


def _cond(expr: str, state: dict) -> bool:
    class _L:
        def __init__(self, s): self.v = _ORDER[s]
        def __le__(self, o): return self.v <= _v(o)
        def __lt__(self, o): return self.v < _v(o)
        def __ge__(self, o): return self.v >= _v(o)
        def __gt__(self, o): return self.v > _v(o)
        def __eq__(self, o): return self.v == _v(o)
        def __hash__(self): return hash(self.v)

    def _v(o):
        return o.v if isinstance(o, _L) else _ORDER.get(o)

    ns = {"true": True, "false": False, "len": len, "all": all, "any": any,
          **{k: _L(k) for k in _ORDER}, **state}
    code = _safe_expr(expr)
    if code is None:
        return False  # refused by the allowlist: not a condition, not taken
    try:
        return bool(eval(code, {"__builtins__": {}}, ns))
    except Exception:
        return False
'''


def _contract_lines(doc: dict) -> list[str]:
    asserts = [(v.get("describe", ""), v["assert"], v.get("phase", ""))
               for v in doc.get("verification") or [] if "assert" in v]
    commands = [(v.get("describe", ""), v["command"])
                for v in doc.get("verification") or [] if "command" in v]
    out = ["#: (describe, assert, phase) — the graph's verification, evaluated by check_contract().",
           "CONTRACT = ["]
    out += [f"    ({d!r}, {a!r}, {ph!r})," for d, a, ph in asserts]
    out += ["]", "#: (describe, command) — checks that run outside the model; listed, not executed.",
            "CONTRACT_COMMANDS = ["]
    out += [f"    ({d!r}, {c!r})," for d, c in commands]
    out += ["]"]
    return out


def _kind_doc(n: dict) -> list[str]:
    """The lines that tell whoever binds this node what kind of node it is.

    `kind: human` and `kind: verifier` compiled to the same stub shape as an
    ordinary LLM node (2026-09-04 audit, D5-04); nothing said 'do not bind a
    model here'.
    """
    if n.get("kind") == "human":
        contract = (n.get("approval") or {}).get("contract", "")
        return ["HUMAN GATE — a person signs this, never a model.",
                f"approval contract: {contract}",
                f"on_timeout: {(n.get('approval') or {}).get('on_timeout', 'reject')}"]
    if n.get("kind") == "verifier":
        return ["VERIFIER — grades the work; its criteria below are what it judges, not what it is scored on."]
    if n.get("kind") == "router":
        return ["ROUTER — first matching out-edge wins."]
    return []


def emit_langgraph(doc: dict) -> str:
    doc = _executable(doc)
    order = {n["id"]: i for i, n in enumerate(doc["nodes"])}
    fanned = {n["id"]: n["fan_out"] for n in doc["nodes"] if n.get("fan_out")}
    out = [f'"""LangGraph build of AGR graph `{doc["name"]}` — generated by `agr adapt`.',
           "", f'Contract: {doc["termination"]["contract"]}', '"""', _PRELUDE]
    if fanned:
        out += ["try:", "    from langgraph.types import Send", "except ImportError:  # older langgraph",
                "    from langgraph.constants import Send", ""]
    out += [*_contract_lines(doc), _CONTRACT_BLOCK]
    has_out: dict[str, list] = {}
    for e in doc["edges"]:
        has_out.setdefault(e["from"], []).append(e)
    terminals = {n["id"] for n in doc["nodes"]
                 if not any(e.get("kind", "flow") == "flow" and order.get(e["to"], 0) > order[n["id"]]
                            for e in has_out.get(n["id"], []))}
    for n in doc["nodes"]:
        abilities = ", ".join(n.get("abilities", []))
        # The stub is where a human or an agent binds behavior, so it is exactly
        # where the rubric has to arrive. Emitting only the speciality handed the
        # implementer a role label and left the domain knowledge in a YAML file
        # they were not reading.
        doc_lines = [*_kind_doc(n), f'speciality: {n["speciality"]} | abilities: {abilities}']
        if n.get("criteria"):
            doc_lines += ["", f'Must judge: {n["criteria"]}']
        if n.get("unbound_ok"):
            doc_lines += ["", f'narrated in the reference runtime: {n["unbound_ok"]}']
        if n.get("fan_out"):
            fo = n["fan_out"]
            doc_lines += ["", f"fan_out: runs once per item of state['{fo['over']}'] (max {fo.get('max', 40)}, "
                              f"on_partial: {fo.get('on_partial', 'continue')}); each call sees "
                              "state['shard'], ['shard_index'], ['shard_count']"]
        body = "\n    ".join(doc_lines)
        fn = _fn(n["id"])
        if n.get("kind") == "human":
            raise_line = (f"    raise PermissionError(\"human approval gate '{n['id']}' requires a person; "
                          f"contract: {(n.get('approval') or {}).get('contract', '')}\")")
        else:
            raise_line = (f"    raise NotImplementedError(\"bind speciality '{n['speciality']}'"
                          f" (abilities: {abilities})\")")
        out += [f"def {fn}(state: dict) -> dict:", f'    """{body}"""', raise_line, ""]
        r = n.get("retries") or {}
        if r.get("max"):
            out += [f"{fn} = _with_retries({fn}, {int(r['max'])}, {bool(r.get('reissue_effects'))})", ""]
        if n["id"] in terminals:
            out += [f"{fn} = _checked({fn})", ""]
    out += ["g = StateGraph(dict)"]
    for n in doc["nodes"]:
        out.append(f'g.add_node("{n["id"]}", {_fn(n["id"])})')
    has_in = {e["to"] for e in doc["edges"]}
    for n in doc["nodes"]:
        if n["id"] not in has_in:
            out.append(f'g.add_edge(START, "{n["id"]}")')
    for n in doc["nodes"]:
        edges = has_out.get(n["id"], [])
        fan_targets = [e["to"] for e in edges if e["to"] in fanned and not e.get("when")]
        approval = (n.get("approval") or {}).get("contract") if n.get("kind") == "human" else None
        if not edges:
            out.append(f'g.add_edge("{n["id"]}", END)')
        elif len(edges) == 1 and fan_targets:
            # R5-04: a map over the fanned-out key, one Send per shard.
            t = fan_targets[0]
            fo = fanned[t]
            ff = "_fan_" + _fn(t)[5:]
            out += [f"def {ff}(state: dict):",
                    f'    items = list(state.get("{fo["over"]}") or [])[: {int(fo.get("max", 40))}]',
                    f'    return [Send("{t}", {{**state, "shard": s, "shard_index": i, '
                    f'"shard_count": len(items)}}) for i, s in enumerate(items)] or END',
                    f'g.add_conditional_edges("{n["id"]}", {ff})']
        elif all(not e.get("when") for e in edges) and not approval:
            out += [f'g.add_edge("{n["id"]}", "{e["to"]}")' for e in edges]
        else:
            rf = "_route_" + _fn(n["id"])[5:]
            pairs = ", ".join(f'("{e["to"]}", {e.get("when")!r})' for e in edges)
            first_match = n.get("kind") == "router"
            out += [f"def {rf}(state: dict):"]
            if approval:
                # R5-05: the approval contract is a guard on leaving the gate.
                out += [f"    if not _cond({approval!r}, state):",
                        f"        return END  # approval not satisfied (on_timeout: "
                        f"{(n.get('approval') or {}).get('on_timeout', 'reject')})"]
            out += [f"    hits = [t for t, w in [{pairs}] if w is None or _cond(w, state)]",
                    ("    return hits[0] if hits else END" if first_match
                     else "    return hits or END"),
                    f'g.add_conditional_edges("{n["id"]}", {rf})']
    out += ["", "app = g.compile()", ""]
    return "\n".join(out)


def emit_crewai(doc: dict) -> str:
    """Compile an AGR graph into runnable-shaped CrewAI source.

    Nodes become Agents (speciality -> role; abilities left as a TODO tool
    list, since AGR abilities are not CrewAI tool objects). Edges become
    Tasks, with any `when` conditions surfaced as conditional-routing notes
    in the task description (CrewAI's sequential Process has no native
    branching primitive). The termination contract becomes the
    `expected_output` of the graph's terminal task(s). Human gates are Tasks
    with `human_input=True`; loop-back edges the sequential process cannot
    take are flagged, never silently dropped (2026-09-04 audit, D5-05); the
    graph's asserts are emitted as `check_contract()` for `run()` to apply.
    """
    doc = _executable(doc)
    order = {n["id"]: i for i, n in enumerate(doc["nodes"])}
    contract = doc.get("termination", {}).get("contract") or f"completion of {doc['name']}"
    out = [f'"""CrewAI build of AGR graph `{doc["name"]}` — generated by `agr adapt --target crewai`.',
           "", f"Contract: {contract}", '"""',
           "from crewai import Agent, Crew, Process, Task", "",
           _AUTOGEN_COND, *_contract_lines(doc), _CONTRACT_BLOCK]

    for n in doc["nodes"]:
        var = _fn(n["id"])
        abilities = ", ".join(n.get("abilities", [])) or "none declared"
        r = n.get("retries") or {}
        out += [f"{var}_agent = Agent(",
                f'    role="{n["speciality"]}",',
                (f'    goal="{_criteria(n)}",' if _criteria(n)
                 else f'    goal="perform the \'{n["id"]}\' step of {doc["name"]}",'),
                f'    backstory="specialised in {n["speciality"]}",',
                f"    tools=[],  # TODO: bind abilities ({abilities}) to real CrewAI tools",
                "    allow_delegation=False,"]
        if r.get("max"):
            out.append(f"    max_retry_limit={int(r['max'])},  # retries.max"
                       + ("; reissue_effects: true" if r.get("reissue_effects") else ""))
        out += [")", ""]

    has_out: dict[str, list] = {}
    for e in doc["edges"]:
        has_out.setdefault(e["from"], []).append(e)
    terminals = {n["id"] for n in doc["nodes"] if n["id"] not in has_out}

    for n in doc["nodes"]:
        var = _fn(n["id"])
        edges = has_out.get(n["id"], [])
        for e in edges:
            if order.get(e["to"], 0) <= order[n["id"]]:
                out.append(f"# NOTE: CrewAI's sequential process cannot re-enter '{e['to']}' from "
                           f"'{n['id']}' (when: {e.get('when')!r}); this loop is dropped — hand-wire it "
                           "or use a hierarchical process.")
        if n.get("fan_out"):
            out.append(f"# NOTE: fan_out over '{n['fan_out']['over']}' is not expressible as one sequential "
                       "Task; the agent receives the whole list and must iterate itself.")
        routes = "; ".join(f'-> {e["to"]} when {e["when"]}' if e.get("when") else f'-> {e["to"]}' for e in edges)
        marker = {"human": "HUMAN GATE", "verifier": "VERIFIER", "router": "ROUTER"}.get(n.get("kind", ""), "")
        desc = (f"{marker}: " if marker else "") + f"execute '{n['id']}' ({n['speciality']})."
        if n.get("kind") == "human":
            desc += f" Approval contract: {(n.get('approval') or {}).get('contract', '')}."
        if routes:
            desc += f" Conditional routing: {routes}."
        expected = contract if n["id"] in terminals else f"structured output consumed by the next step in {doc['name']}"
        out += [f"{var}_task = Task(",
                f'    description="{desc}",',
                f'    expected_output="{expected}",',
                f"    agent={var}_agent,"]
        if n.get("kind") == "human":
            out.append("    human_input=True,  # a person answers this task; never auto-bind a model")
        out += [")", ""]

    agents = ", ".join(f"{_fn(n['id'])}_agent" for n in doc["nodes"])
    tasks = ", ".join(f"{_fn(n['id'])}_task" for n in doc["nodes"])
    out += ["crew = Crew(", f"    agents=[{agents}],", f"    tasks=[{tasks}],",
            "    process=Process.sequential,", ")", "",
            "", "def run(inputs: dict):",
            '    """kickoff, then apply the graph\'s contract to what came back."""',
            "    result = crew.kickoff(inputs=inputs)",
            '    state = {**inputs, **(getattr(result, "json_dict", None) or {})}',
            "    return result, check_contract(state)", ""]
    return "\n".join(out)


_AUTOGEN_COND = _EMITTED_GUARD + '''\
def _cond(expr: str, state: dict) -> bool:
    class _L:
        def __init__(self, s): self.v = _ORDER[s]
        def __le__(self, o): return self.v <= _v(o)
        def __lt__(self, o): return self.v < _v(o)
        def __ge__(self, o): return self.v >= _v(o)
        def __gt__(self, o): return self.v > _v(o)
        def __eq__(self, o): return self.v == _v(o)
        def __hash__(self): return hash(self.v)

    def _v(o):
        return o.v if isinstance(o, _L) else _ORDER.get(o)

    ns = {"true": True, "false": False, "len": len, "all": all, "any": any,
          **{k: _L(k) for k in _ORDER}, **state}
    code = _safe_expr(expr)
    if code is None:
        return False  # refused by the allowlist: not a condition, not taken
    try:
        return bool(eval(code, {"__builtins__": {}}, ns))
    except Exception:
        return False
'''


def emit_autogen(doc: dict) -> str:
    doc = _executable(doc)
    """Compile an AGR graph into runnable-shaped AutoGen source.

    Nodes become ConversableAgent/AssistantAgent definitions. Router-kind
    nodes' outgoing `when` conditions are encoded into a GroupChat
    speaker-selection function (`_select_speaker`), reusing the same
    Level-aware condition evaluator the LangGraph emitter embeds. The
    termination contract becomes each agent's `is_termination_msg`.
    """
    contract = doc.get("termination", {}).get("contract") or f"completion of {doc['name']}"
    out = [f'"""AutoGen build of AGR graph `{doc["name"]}` — generated by `agr adapt --target autogen`.',
           "", f"Contract: {contract}", '"""',
           "from autogen import AssistantAgent, ConversableAgent, GroupChat, GroupChatManager", "",
           '_ORDER = {"trivial": -1, "low": 0, "simple": 0, "medium": 1, "moderate": 1,',
           '          "high": 2, "complex": 2, "critical": 3}', ""]

    out += ['def is_termination_msg(msg: dict) -> bool:',
            f'    """Contract: {contract}"""',
            '    return isinstance(msg, dict) and bool(msg.get("terminate"))', ""]

    for n in doc["nodes"]:
        var = _fn(n["id"])
        abilities = ", ".join(n.get("abilities", [])) or "none declared"
        cls = "ConversableAgent" if n.get("kind") == "human" else "AssistantAgent"
        out += [f"{var} = {cls}(",
                f'    name="{n["id"]}",',
                (f'    system_message="You are a {n["speciality"]} agent. Abilities: '
                 f'{abilities}. Must judge: {_criteria(n)}",' if _criteria(n) else
                 f'    system_message="You are a {n["speciality"]} agent. Abilities: {abilities}.",'),
                "    is_termination_msg=is_termination_msg,", ")", ""]

    has_out: dict[str, list] = {}
    for e in doc["edges"]:
        has_out.setdefault(e["from"], []).append(e)

    out += ["def _select_speaker(last_speaker, groupchat):",
            '    """Speaker selection encoding AGR edge conditions (`when`) as Python."""',
            '    state = groupchat.messages[-1].get("state", {}) if groupchat.messages else {}',
            "    routes = {"]
    for node_id, edges in has_out.items():
        pairs = ", ".join(f'("{e["to"]}", {e.get("when")!r})' for e in edges)
        out.append(f'        "{node_id}": [{pairs}],')
    out += ["    }",
            "    agents = {a.name: a for a in groupchat.agents}",
            '    for to, when in routes.get(getattr(last_speaker, "name", None), []):',
            "        if when is None or _cond(when, state):",
            "            return agents.get(to)",
            "    return None", ""]
    out.append(_AUTOGEN_COND)
    out += [*_contract_lines(doc), _CONTRACT_BLOCK]

    agent_vars = ", ".join(_fn(n["id"]) for n in doc["nodes"])
    max_steps = doc.get("termination", {}).get("max_steps", 10)
    out += [f"groupchat = GroupChat(agents=[{agent_vars}], messages=[], max_round={max_steps},",
            "                      speaker_selection_method=_select_speaker)",
            "manager = GroupChatManager(groupchat=groupchat)", ""]
    return "\n".join(out)
