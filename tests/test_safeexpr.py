"""The expression evaluator is a security boundary, so it is tested like one.

Until v1.8 `edges[].when` and `verification[].assert` reached `eval()` with
`{"__builtins__": {}}`, which is not a sandbox. A graph is a downloaded
artifact — from this registry, a PR, or an agent — so `agr eval` on a
contributed graph ran arbitrary code. These tests pin the three places that
must refuse it: the gate, the runtime, and the code the adapters emit.
"""
from __future__ import annotations

import ast

import pytest
import yaml

from agenticgraphs import safeexpr
from agenticgraphs.adapters import emit_autogen, emit_langgraph
from agenticgraphs.harness import MockRunner, run_graph, safe_eval
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import iter_graphs, load
from agenticgraphs.safeexpr import UnsafeExpression
from agenticgraphs.validate import _lint_expressions

#: The published `{"__builtins__": {}}` escape, plus the shapes it mutates into.
ESCAPES = [
    "().__class__.__bases__[0].__subclasses__()",
    "[c for c in ().__class__.__bases__[0].__subclasses__() if c.__name__ == 'Popen']",
    "output.ok.__class__",
    "''.__class__.__mro__[1].__subclasses__()",
    "output.get.__globals__",
    "[].__len__()",
    "open('/etc/passwd')",
    "__import__('os')",
]

#: Real expressions from the registry. The allowlist is worth nothing if it
#: also refuses the 214 expressions the graphs actually use.
REAL = [
    "output.verdict in ['approve', 'request_changes']",
    "all(f.file and f.line for f in output.findings)",
    "complexity <= moderate",
    "risk >= medium and not exploit_blocked",
    "len(output.findings) > 0",
    "abs(output.claimed_effect - output.recomputed_effect) < 0.05",
    "not exploit_blocked and attempts < 3",
    "all(e.get('file') for e in output.findings)",
]


@pytest.mark.parametrize("expr", ESCAPES)
def test_gate_refuses_every_known_escape(expr):
    assert safeexpr.check(expr), f"allowlist accepted an escape: {expr}"


@pytest.mark.parametrize("expr", REAL)
def test_gate_accepts_every_shape_the_registry_uses(expr):
    assert safeexpr.is_safe(expr), f"allowlist refused a real expression: {expr}"


@pytest.mark.parametrize("expr", ESCAPES)
def test_runtime_raises_rather_than_scoring_an_escape(expr):
    """Refusal must not look like a failed assert.

    Returning False would let a hostile graph read as merely a low-scoring one —
    the one signal that must never blend into the pass rate.
    """
    with pytest.raises(UnsafeExpression):
        safe_eval(expr, {"output": {"ok": True}})


def test_every_registry_expression_survives_the_allowlist():
    """The boundary and the corpus must agree, or the gate is unshippable."""
    for g in iter_graphs():
        doc = load(g)
        assert _lint_expressions(doc) == [], doc["name"]


def test_end_to_end_a_hostile_graph_is_rejected_at_the_gate_and_at_runtime(tmp_path):
    doc = yaml.safe_load("""
apiVersion: agr/v1.7
name: hostile
description: A graph that looks ordinary.
category: business-ops
nodes:
- {id: work, speciality: producer, abilities: [generate], outputs: [ok]}
- {id: verify, speciality: critic, abilities: [critique], kind: verifier, outputs: [ok, output]}
edges: [{from: work, to: verify}]
termination: {max_steps: 4, contract: the work is correct}
verification:
- assert: "output.ok or ().__class__.__bases__[0].__subclasses__()"
""")
    assert _lint_expressions(doc), "gate accepted a hostile graph"
    runner = MockRunner({"work": {"ok": False}, "verify": {"ok": False, "output": {"ok": False}}})
    with pytest.raises(UnsafeExpression):
        run_graph(doc, runner)


def test_hostile_edge_condition_is_refused_not_silently_untaken():
    """`edge_true` swallows unresolvable conditions; it must not swallow this one."""
    doc = yaml.safe_load("""
apiVersion: agr/v1.7
name: hostile-edge
description: A graph whose routing condition is an escape.
category: business-ops
nodes:
- {id: work, speciality: producer, abilities: [generate], outputs: [ok]}
- {id: verify, speciality: critic, abilities: [critique], kind: verifier, outputs: [ok, output]}
edges: [{from: work, to: verify, when: "().__class__.__bases__[0].__subclasses__()"}]
termination: {max_steps: 4, contract: the work is correct}
verification: [{assert: output.ok}]
""")
    assert _lint_expressions(doc)
    with pytest.raises(UnsafeExpression):
        run_graph(doc, MockRunner({"work": {"ok": True}}))


@pytest.mark.parametrize("emit", [emit_langgraph, emit_autogen])
def test_emitted_modules_do_not_ship_a_bare_eval(emit):
    """Generated code is code the user runs. It carries the guard, not the hole."""
    src = emit(load(find_graph("incident-triage-router")))
    ast.parse(src)
    assert "_safe_expr" in src
    assert 'eval(expr, {"__builtins__": {}}' not in src


def test_emitted_guard_actually_refuses_an_escape():
    """Compile-and-run the inlined guard, not just grep for it."""
    src = emit_langgraph(load(find_graph("incident-triage-router")))
    guard = src[src.index("import ast as _ast"): src.index("from langgraph.graph")]
    ns: dict = {}
    exec(compile(guard, "<guard>", "exec"), ns)  # noqa: S102 — the artifact under test
    assert ns["_safe_expr"]("().__class__.__bases__[0]") is None
    assert ns["_safe_expr"]("complexity <= moderate") is not None


def test_callable_allowlist_matches_the_runtime_namespace():
    """A callable the allowlist permits but the namespace lacks fails at runtime;
    one the namespace has but the allowlist omits is a silently unusable feature.
    Keeping them in sync is what makes the refusal message truthful."""
    from agenticgraphs.harness import _SAFE

    callable_safe = {k for k, v in _SAFE.items() if callable(v) and not isinstance(v, bool)}
    assert safeexpr._CALLABLE_NAMES <= callable_safe


def test_emitted_guard_and_module_guard_share_one_callable_allowlist():
    src = emit_langgraph(load(find_graph("incident-triage-router")))
    guard = src[src.index("import ast as _ast"): src.index("from langgraph.graph")]
    ns: dict = {}
    exec(compile(guard, "<guard>", "exec"), ns)  # noqa: S102 — the artifact under test
    assert ns["_CALLABLE_NAMES"] == set(safeexpr._CALLABLE_NAMES)
