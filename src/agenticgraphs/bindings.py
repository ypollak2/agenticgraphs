"""Bind abilities to real implementations, so a node can obtain facts it cannot invent.

Every run in this repo's history sent a prompt and parsed JSON. That is why 18 of
28 remaining composite assert failures demand a *grounded provenance field* — a
URL that resolves, a command's exit code, a file and line number. A model cannot
produce those honestly, and one that appeared to would be fabricating them.

The seam for this shipped in M0 and was never used: `spec/agr-ability.schema.json`
has carried `binding: {kind, ref}` since the first commit, and 0 of 32 abilities
declared one. This fills that seam rather than inventing a parallel mechanism.

**Bounded on purpose.** A node declares which abilities it has; only those are
resolved and offered. Handing a model an open toolbox would discard the property
that makes these graphs auditable — that what a node may do is written down.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .registry import ROOT, iter_yaml, load

#: Risk levels that mutate something. Bound only when the caller opts in, the
#: same gate `agr eval --run-commands` already uses for verification commands.
MUTATING = {"write", "execute"}


class BindingError(Exception):
    """An ability cannot be bound as requested."""


@dataclass
class ToolCall:
    """One grounded fact, and where it came from.

    Recorded whether or not the model uses the result: the point of an
    ability-bound run is that a claim can be traced, and a trace that only exists
    for successful calls is not a trace.
    """

    ability: str
    args: dict
    ok: bool
    detail: str
    evidence: dict = field(default_factory=dict)


# --------------------------------------------------------------------- builtins


def _run_command(args: dict, cwd: Path, rep_calls: list) -> dict:
    """`run_command` — the exit code is the fact, not the prose about it."""
    cmd = args.get("command", "")
    if not cmd:
        raise BindingError("run_command needs a 'command'")
    try:
        proc = subprocess.run(
            shlex.split(cmd), cwd=cwd, capture_output=True, text=True,
            timeout=120, check=False,
        )
    except (OSError, subprocess.SubprocessError) as ex:
        return {"exit_code": None, "error": f"{type(ex).__name__}: {ex}"}
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2000:],
        "command": cmd,
    }


def _read_diff(args: dict, cwd: Path, rep_calls: list) -> dict:
    """`read_diff` — returns real file+line pairs, which is what the asserts want."""
    ref = args.get("ref", "HEAD")
    path = args.get("path")
    cmd = ["git", "diff", "--unified=0", ref]
    if path:
        cmd += ["--", path]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as ex:
        # Same contract as `_run_command`: a hung or missing git is a fact the
        # caller gets back, not a run that never returns (2026-09-04 audit, D3-02).
        return {"hunks": [], "files": [], "error": f"{type(ex).__name__}: {ex}"}
    hunks, current = [], None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("@@") and current:
            try:
                start = int(line.split("+")[1].split(",")[0].split(" ")[0])
            except (IndexError, ValueError):
                continue
            hunks.append({"file": current, "line": start})
    return {"hunks": hunks, "files": sorted({h["file"] for h in hunks})}


def _web_search(args: dict, cwd: Path, rep_calls: list) -> dict:
    """`web_search` — a URL that resolves, plus the date it was fetched.

    Deliberately minimal: it resolves a query to real, reachable URLs rather than
    pretending to be a search product. `source_url` failing an assert because
    nothing was fetched is a truthful result; a plausible-looking invented URL is
    the exact failure this module exists to stop.
    """
    query = args.get("query", "")
    if not query:
        raise BindingError("web_search needs a 'query'")
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": "agenticgraphs/0.7"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
            body = r.read(200_000).decode("utf-8", "replace")
    except Exception as ex:
        return {"results": [], "error": f"{type(ex).__name__}: {ex}"}
    import re
    from datetime import date

    found, seen = [], set()
    for m in re.finditer(r'href="(https?://[^"?]+)"', body):
        u = m.group(1)
        if "duckduckgo.com" in u or u in seen:
            continue
        seen.add(u)
        found.append({"source_url": u, "source_date": date.today().isoformat()})
        if len(found) >= 8:
            break
    return {"results": found}


# Public names: what `abilities/*.yaml` `binding.ref` points at
# (`agenticgraphs.bindings:run_command`). The refs pointed at symbols that did
# not exist and nothing read them (2026-09-04 audit, D2-02).
run_command = _run_command
read_diff = _read_diff
web_search = _web_search

#: Name -> callable for the abilities this module implements. Since R3-03 the
#: authoritative map is `resolve_binding()` over each ability's declared
#: `binding.ref`; this table is what those refs resolve to and the fallback for a
#: YAML that declares no binding at all.
BUILTINS = {
    "run_command": _run_command,
    "read_diff": _read_diff,
    "web_search": _web_search,
}


def resolve_binding(doc: dict):
    """The callable an ability's `binding` declares, or None.

    `kind: builtin` refs are `module:attr` and are imported here, so a YAML that
    names a symbol that does not exist fails loudly (`agr validate` runs this
    through `lint_ability`). `mcp_tool` and `shell` have no resolver yet and
    resolve to None: an ability that declares one is not bound, and says so.
    """
    b = doc.get("binding") or {}
    if b.get("kind") != "builtin":
        return None
    ref = b.get("ref", "")
    if ":" not in ref:
        raise BindingError(f"{doc.get('name')}: binding.ref {ref!r} is not module:attr")
    mod, attr = ref.split(":", 1)
    import importlib

    try:
        target = getattr(importlib.import_module(mod), attr)
    except (ImportError, AttributeError) as ex:
        raise BindingError(f"{doc.get('name')}: binding.ref {ref!r} does not resolve ({ex})") from ex
    if not callable(target):
        raise BindingError(f"{doc.get('name')}: binding.ref {ref!r} is not callable")
    return target

#: JSON Schema fragments the model sees. Kept narrow — a node may only do what its
#: ability says it does.
SCHEMAS = {
    "run_command": {"command": "shell command to execute"},
    "read_diff": {"ref": "git ref to diff against (default HEAD)",
                  "path": "optional path filter"},
    "web_search": {"query": "search query"},
}


def available(allow_mutating: bool = False, root: Path = ROOT) -> dict[str, dict]:
    """Abilities that can be bound right now, keyed by name.

    An ability is bindable when a builtin exists for it *and* its declared risk is
    permitted. Risk lives in `abilities/<name>.yaml` and has since M0 — this reads
    the existing declaration rather than adding a second permission model.
    """
    out: dict[str, dict] = {}
    for path in iter_yaml("abilities", root):
        doc = load(path)
        name = doc["name"]
        fn = resolve_binding(doc) if doc.get("binding") else BUILTINS.get(name)
        if fn is None:
            continue
        risk = doc.get("risk", "read")
        if risk in MUTATING and not allow_mutating:
            continue
        out[name] = {"risk": risk, "schema": SCHEMAS.get(name, {}),
                     "description": doc["description"], "fn": fn}
    return out


def bind_for(node: dict, allow_mutating: bool = False, root: Path = ROOT) -> dict[str, dict]:
    """The subset of `available()` this node actually declares."""
    declared = set(node.get("abilities") or [])
    return {k: v for k, v in available(allow_mutating, root).items() if k in declared}


def invoke(ability: str, args: dict, cwd: Path, allow_mutating: bool = False,
           root: Path = ROOT) -> ToolCall:
    """Run one bound ability and return the call record."""
    bound = available(allow_mutating, root)
    if ability not in bound:
        return ToolCall(ability, args, False,
                        f"'{ability}' is not bound (unknown, or its risk requires --allow-tools)")
    try:
        evidence = bound[ability]["fn"](args, cwd, [])
    except BindingError as ex:
        return ToolCall(ability, args, False, str(ex))
    except Exception as ex:
        return ToolCall(ability, args, False, f"{type(ex).__name__}: {ex}")
    return ToolCall(ability, args, True, "ok", evidence)


def as_openai_tools(bound: dict[str, dict]) -> list[dict]:
    """Bound abilities as OpenAI tool definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": {
                    "type": "object",
                    "properties": {k: {"type": "string", "description": v}
                                   for k, v in spec["schema"].items()},
                    "required": list(spec["schema"])[:1],
                },
            },
        }
        for name, spec in sorted(bound.items())
    ]


def digest(call: ToolCall) -> str:
    """A short, loggable trace of one call — never the full payload."""
    body = json.dumps(call.evidence, default=str)
    return f"{call.ability}({json.dumps(call.args, default=str)[:80]}) -> {body[:120]}"
