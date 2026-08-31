"""AST-allowlist evaluator for graph expressions.

`edges[].when` and `verification[].assert` are strings authored in a graph.yaml,
and a graph.yaml is a thing you *download* — from this registry, from a PR, from
an agent that wrote one. Until v1.8 both were handed to `eval()` with
`{"__builtins__": {}}`, which is not a sandbox: `().__class__.__bases__[0]
.__subclasses__()` walks straight back to `Popen`, so any contributed graph could
run arbitrary code the moment someone typed `agr eval`. The `run_command` risk
gate in `bindings.py` did not apply — this path never consulted it.

The fix is to stop treating the expression as Python and start treating it as the
tiny expression language it always was. `compile_expr` walks the parse tree and
refuses anything outside `_ALLOWED`; `validate` runs the same walk so a hostile
assert is rejected by the gate, not discovered by the runtime.

The allowlist is derived from what the registry actually uses (214 expressions:
Compare, BoolOp, Attribute, Call to len/all/abs and `.get`, one Subscript-with-
Slice, three BinOp). It is deliberately smaller than "safe Python" — a contract
that needs a construct this rejects is a contract that wants a
`verification[].command` instead.
"""
from __future__ import annotations

import ast

#: Node types an expression may contain. Anything absent is refused, so a new
#: Python grammar feature is denied by default rather than allowed by omission.
_ALLOWED: tuple[type[ast.AST], ...] = (
    ast.Expression,
    # boolean / comparison spine
    ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.IfExp,
    ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Is, ast.IsNot, ast.In, ast.NotIn,
    # arithmetic used by tolerance asserts (`abs(a - b) < 0.05`)
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
    # data access
    ast.Name, ast.Load, ast.Attribute, ast.Constant,
    ast.Subscript, ast.Slice, ast.Index if hasattr(ast, "Index") else ast.Slice,
    ast.List, ast.Tuple, ast.Set, ast.Dict,
    # quantifiers: `all(f.file for f in output.findings)`
    ast.Call, ast.GeneratorExp, ast.ListComp, ast.SetComp,
    ast.comprehension, ast.Store,
)

#: The only attribute a call may target. `output.findings` is data; `x.get('k')`
#: is the one method the registry uses, and it cannot reach the interpreter.
_CALLABLE_ATTRS = frozenset({"get"})

#: The only bare names a call may target. Without this, `open('/etc/passwd')` is
#: structurally identical to `len(x)` and passes the walk — stopped only by the
#: closed namespace at eval time. Defence that lives solely in the namespace is
#: defence that any future caller can drop by passing a richer one, so the
#: allowlist names the callables too. Must stay a subset of `harness._SAFE`;
#: `test_callable_allowlist_matches_the_runtime_namespace` enforces that.
_CALLABLE_NAMES = frozenset({"len", "all", "any", "sum", "min", "max", "abs", "round"})

#: Attribute names are how every published `eval` escape starts. Blocking the
#: dunder prefix is what makes `Attribute` safe to allow at all.
_FORBIDDEN_PREFIX = "_"


class UnsafeExpression(ValueError):
    """The expression contains a construct the evaluator refuses to run."""


def check(expr: str) -> list[str]:
    """Reasons `expr` may not be evaluated. Empty list means it is accepted.

    A syntax error is not reported here — `lint: verification assert is not a
    parseable expression` already covers that, and returning it twice would make
    one fault look like two.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return []

    reasons: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            reasons.append(f"{type(node).__name__} is not permitted in an expression")
            continue
        if isinstance(node, ast.Attribute) and node.attr.startswith(_FORBIDDEN_PREFIX):
            reasons.append(f"attribute '{node.attr}' is not permitted")
        elif isinstance(node, ast.Name) and node.id.startswith(_FORBIDDEN_PREFIX):
            reasons.append(f"name '{node.id}' is not permitted")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute):
                if fn.attr not in _CALLABLE_ATTRS:
                    reasons.append(
                        f"calling method '{fn.attr}' is not permitted "
                        f"(allowed: {', '.join(sorted(_CALLABLE_ATTRS))})"
                    )
            elif isinstance(fn, ast.Name):
                if fn.id not in _CALLABLE_NAMES:
                    reasons.append(
                        f"calling '{fn.id}' is not permitted "
                        f"(allowed: {', '.join(sorted(_CALLABLE_NAMES))})"
                    )
            else:
                reasons.append("only a plain name or `.get` may be called")
            if node.keywords:
                reasons.append("keyword arguments are not permitted")
    # Dedupe while keeping order: one malformed expression should read as one
    # finding per distinct cause, not once per occurrence.
    seen: set[str] = set()
    return [r for r in reasons if not (r in seen or seen.add(r))]


def is_safe(expr: str) -> bool:
    return not check(expr)


def compile_expr(expr: str):
    """Compile `expr` after the allowlist walk, or raise `UnsafeExpression`.

    Callers still supply a closed namespace — the allowlist removes the escape,
    the namespace decides what the expression can see.
    """
    reasons = check(expr)
    if reasons:
        raise UnsafeExpression(f"{expr[:70]}: " + "; ".join(reasons))
    return compile(ast.parse(expr, mode="eval"), "<agr-expr>", "eval")
