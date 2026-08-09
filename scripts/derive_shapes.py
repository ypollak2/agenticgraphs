"""Derive an output's shape from the assert that reads it.

`derive_outputs.py` learned which node produces a key from the golden fixtures.
This learns the key's *shape* from the contract, because the contract already
states it:

    all(f.file and f.line for f in output.findings)
        -> findings: list[{file:str, line:int}]

    all(s.exit_code == 0 for s in output.steps)
        -> steps: list[{exit_code:int}]

That is the registry telling us what it meant, not a guess. Every one of the nine
unsatisfiable composites types **zero** of its outputs, and the pilot graph moved
from `'str' has no attribute 'exit_code'` to an honest `exit_code: 1` purely by
being typed.

**No assert is ever modified.** The temptation with nine failing graphs is to
delete the clause that fails; this only adds shapes.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import ROOT, iter_graphs, load  # noqa: E402
from agenticgraphs.shapes import declared  # noqa: E402
from agenticgraphs.subgraphs import expand, has_subgraphs  # noqa: E402

#: Field-name conventions the registry already uses consistently. Anything not
#: listed defaults to `str`, which is the weakest useful claim rather than a guess
#: dressed up as knowledge.
INT_FIELDS = {"line", "exit_code", "count", "page_count", "page_limit", "index"}
BOOL_FIELDS = {
    "matches_transcript", "answered", "flagged", "validated", "resolves",
    "matches_ownership_map", "reproduces_resolution", "duplicates_deduped",
}


def _field_type(name: str) -> str:
    """Leaf type, defaulting to the weakest useful claim.

    The value of typing here is `list[{...}]` — records rather than prose — not
    the leaf types. Defaulting to `str` would reject a legitimate `true` and
    manufacture violations out of a guess; `any` still forces the record
    structure, which is the thing the asserts actually need.
    """
    if name in INT_FIELDS:
        return "int"
    if name in BOOL_FIELDS or name.startswith(("is_", "has_")):
        return "bool"
    return "any"


def shapes_from_assert(expr: str) -> dict[str, str]:
    """`{key: shape}` for every `output.<key>` the expression iterates or indexes.

    Only comprehensions are inferred as record lists — `for f in output.findings`
    with `f.file` inside is unambiguous. A bare `output.verdict` says nothing about
    type and is deliberately left untyped rather than assumed.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return {}
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.GeneratorExp, ast.ListComp)):
            continue
        for gen in node.generators:
            src = gen.iter
            if not (isinstance(src, ast.Attribute) and isinstance(src.value, ast.Name)
                    and src.value.id == "output"):
                continue
            if not isinstance(gen.target, ast.Name):
                continue
            var, key = gen.target.id, src.attr
            fields: dict[str, str] = {}
            for inner in ast.walk(node):
                # `f.file`
                if (isinstance(inner, ast.Attribute) and isinstance(inner.value, ast.Name)
                        and inner.value.id == var
                        and inner.attr != "get"):  # `e.get('log_id')` is a call, not a field
                    fields[inner.attr] = _field_type(inner.attr)
                # `e.get('log_id')`
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "get"
                        and isinstance(inner.func.value, ast.Name)
                        and inner.func.value.id == var
                        and inner.args and isinstance(inner.args[0], ast.Constant)):
                    fields[str(inner.args[0].value)] = _field_type(str(inner.args[0].value))
            if fields:
                body = ", ".join(f"{k}:{v}" for k, v in sorted(fields.items()))
                out[key] = f"list[{{{body}}}]"
    return out


def apply(gpath: Path) -> list[str]:
    doc = load(gpath)
    exp = expand(doc, ROOT) if has_subgraphs(doc) else doc

    wanted: dict[str, str] = {}
    for v in exp.get("verification") or []:
        if "assert" in v:
            wanted.update(shapes_from_assert(v["assert"]))
    if not wanted:
        return []

    # Attribute each shape to the node that declares the key. In a composite the
    # producing node may live inside a phase, so map a prefixed id back to its phase.
    by_id = {n["id"]: n for n in doc["nodes"]}
    added: list[str] = []
    for key, shape in sorted(wanted.items()):
        owner = next((n["id"] for n in exp["nodes"] if key in declared(n)), None)
        if owner is None:
            continue
        target = by_id.get(owner) or by_id.get(owner.split(".")[0])
        if target is None:
            continue
        current = declared(target)
        if current.get(key) is not None:
            continue  # already typed; never overwrite an author's choice
        target["outputs"] = [
            {k: (shape if k == key else s)} if (s or k == key) else k
            for k, s in current.items()
        ]
        added.append(f"{target['id']}.{key}: {shape}")

    if added:
        gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    return added


def main() -> int:
    total = 0
    for gpath in iter_graphs():
        for line in apply(gpath):
            total += 1
            print(f"  {load(gpath)['name']:34s} {line}")
    print(f"\ntyped {total} outputs from the asserts that read them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
