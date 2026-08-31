"""Typed outputs — a contract that names a key and never its type is half a contract.

Six versions of findings reduce to the same sentence. `outputs: [examples]` says a
node produces `examples`; it never said `examples` is a list of records carrying an
`exit_code`. So `gpt-4o` ran 20 real commands, summarised them into English, and
returned a list of prose sentences — at which point
`all(e.exit_code == 0 for e in output.examples)` fails on `'str' object has no
attribute 'exit_code'`. The model satisfied every declaration it was given.

The shape language is deliberately tiny. It exists to be *stated in a prompt* and
*checked at runtime*, not to become a type system:

    str  int  float  bool  list  dict  any
    list[int]                       homogeneous list
    list[{exit_code:int, file:str}] list of records — the case the asserts need
    {verdict:str}                   a record

Backwards compatible: an entry stays a bare string when the shape is unknown.

    outputs:
      - patch                                    # untyped, as before
      - examples: list[{exit_code:int}]          # typed
"""
from __future__ import annotations

import re

#: `float` accepts an int too, so a value is checked against a tuple of types —
#: which is why this is annotated as isinstance's `_ClassInfo`, not `type`.
SCALARS: dict[str, type | tuple[type, ...]] = {
    "str": str, "int": int, "float": (int, float), "bool": bool,
    "list": list, "dict": dict, "any": object,
}

_RECORD = re.compile(r"^\{(.*)\}$", re.S)
_LIST = re.compile(r"^list\[(.*)\]$", re.S)


class ShapeError(Exception):
    """A shape expression is not well-formed."""


def parse(expr: str) -> dict:
    """Compile a shape expression into a checkable descriptor."""
    expr = (expr or "").strip()
    if not expr:
        raise ShapeError("empty shape")
    if m := _LIST.match(expr):
        return {"kind": "list", "items": parse(m.group(1))}
    if m := _RECORD.match(expr):
        fields = {}
        for part in _split_fields(m.group(1)):
            if ":" not in part:
                raise ShapeError(f"record field '{part}' needs a type")
            name, typ = part.split(":", 1)
            fields[name.strip()] = parse(typ)
        if not fields:
            raise ShapeError("record shape has no fields")
        return {"kind": "record", "fields": fields}
    if expr in SCALARS:
        return {"kind": "scalar", "name": expr}
    raise ShapeError(f"unknown shape '{expr}'")


def _split_fields(body: str) -> list[str]:
    """Split on commas that are not inside a nested brace or bracket."""
    out, depth, cur = [], 0, ""
    for ch in body:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [p for p in (x.strip() for x in out) if p]


def declared(node: dict) -> dict[str, str | None]:
    """`{name: shape-expression-or-None}` for a node's declared outputs."""
    out: dict[str, str | None] = {}
    for entry in node.get("outputs") or []:
        if isinstance(entry, str):
            out[entry] = None
        elif isinstance(entry, dict) and len(entry) == 1:
            (name, shape), = entry.items()
            out[name] = str(shape)
    return out


def names(node: dict) -> list[str]:
    """Just the key names — what every caller before typed outputs expected."""
    return list(declared(node))


def check(value, shape: dict, path: str = "") -> list[str]:
    """Where `value` departs from `shape`. Empty means it conforms."""
    where = f" at {path}" if path else ""
    if shape["kind"] == "scalar":
        name = shape["name"]
        if name == "any":
            return []
        expected = SCALARS[name]
        # bool is an int in Python; an assert asking for a count does not want True.
        if name in ("int", "float") and isinstance(value, bool):
            return [f"expected {name}{where}, got bool"]
        if not isinstance(value, expected):
            return [f"expected {name}{where}, got {type(value).__name__}"]
        return []
    if shape["kind"] == "list":
        if not isinstance(value, list):
            return [f"expected list{where}, got {type(value).__name__}"]
        problems: list[str] = []
        for i, item in enumerate(value):
            problems += check(item, shape["items"], f"{path}[{i}]")
        return problems[:5]  # a wrong list is wrong; 200 identical lines help nobody
    if not isinstance(value, dict):
        return [f"expected an object{where}, got {type(value).__name__}"]
    problems = []
    for field, sub in shape["fields"].items():
        if field not in value:
            problems.append(f"missing '{field}'{where}")
        else:
            problems += check(value[field], sub, f"{path}.{field}" if path else field)
    return problems[:5]


def violations(node: dict, out: dict) -> list[str]:
    """Shape violations in one node's output. Untyped declarations are skipped.

    A declared shape describes **one execution** of the node. A `fan_out` node
    runs once per shard and v1.2 merges those into a list, so its declared shape
    is checked as `list[<shape>]` — the declaration stays readable as the thing a
    single shard produces, which is what its author and the model both think about.
    """
    fanned = bool(node.get("fan_out"))
    problems: list[str] = []
    for name, expr in declared(node).items():
        if expr is None or name not in out:
            continue
        try:
            shape = parse(expr)
        except ShapeError as ex:
            problems.append(f"{node['id']}.{name}: {ex}")
            continue
        if fanned:
            shape = {"kind": "list", "items": shape}
        problems += [f"{node['id']}.{name}: {p}" for p in check(out[name], shape, "")]
    return problems


def describe(node: dict) -> str:
    """The shape contract as a prompt line — the whole point of typing them.

    A model told `examples` is `list[{exit_code:int}]` returns records. Told only
    that it must return `examples`, it returns whatever it feels like, which on
    the pilot run was English prose.
    """
    typed = {k: v for k, v in declared(node).items() if v}
    if not typed:
        return ""
    parts = ", ".join(f"{k} must be {v}" for k, v in sorted(typed.items()))
    return f"Shapes: {parts}. Use exactly these types — not prose descriptions of them. "
