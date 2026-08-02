"""M1 eval harness: execute AGR graphs against a runner and verify contracts.

The interpreter is real (routers, joins, bounded loops, verification asserts).
Runners are pluggable: MockRunner replays golden fixtures (measures graph/contract
mechanics), LLMRunner calls any OpenAI-compatible endpoint (measures model quality).
Every profile records which runner produced it — mock results are marked provisional.
"""
from __future__ import annotations

import json
import os
import urllib.request
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field

_ORDER = {"trivial": -1, "low": 0, "simple": 0, "medium": 1, "moderate": 1,
          "high": 2, "complex": 2, "critical": 3}


class Level:
    """Ordered qualitative literal so conditions like `risk >= medium` evaluate."""

    def __init__(self, s: str):
        self.s, self.v = s, _ORDER[s]

    def _v(self, o):
        return o.v if isinstance(o, Level) else _ORDER.get(o)

    def __eq__(self, o):  # noqa: D105
        return self._v(o) == self.v

    def __le__(self, o):
        return self.v <= self._v(o)

    def __lt__(self, o):
        return self.v < self._v(o)

    def __ge__(self, o):
        return self.v >= self._v(o)

    def __gt__(self, o):
        return self.v > self._v(o)

    def __hash__(self):
        return hash(self.v)

    def __repr__(self):
        return f"Level({self.s})"


class DotDict(dict):
    """dict with attribute access, so asserts can say `output.verdict`."""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e


def wrap(v):
    if isinstance(v, dict):
        return DotDict({k: wrap(x) for k, x in v.items()})
    if isinstance(v, list):
        return [wrap(x) for x in v]
    return v


_SAFE = {"len": len, "all": all, "any": any, "sum": sum, "min": min, "max": max,
         "abs": abs, "round": round, "true": True, "false": False, "null": None,
         **{name: Level(name) for name in _ORDER}}


def safe_eval(expr: str, bb: dict):
    ns = {**_SAFE, **wrap(dict(bb))}
    return eval(expr, {"__builtins__": {}}, ns)  # noqa: S307 — namespace is closed


def edge_true(when: str | None, bb: dict) -> bool:
    if not when:
        return True
    try:
        return bool(safe_eval(when, bb))
    except Exception:
        return False  # unresolvable condition = edge not taken


@dataclass
class RunReport:
    trace: list[str] = field(default_factory=list)
    steps: int = 0
    assert_failures: list[str] = field(default_factory=list)
    skipped_commands: int = 0
    hit_step_cap: bool = False

    @property
    def passed(self) -> bool:
        return not self.assert_failures and not self.hit_step_cap


class MockRunner:
    """Replays per-node fixture outputs; a list means successive visits."""

    name = "mock"

    def __init__(self, node_outputs: dict):
        self.node_outputs, self.visits = node_outputs, defaultdict(int)

    def run(self, node: dict, bb: dict) -> dict:
        out = self.node_outputs.get(node["id"], {})
        if isinstance(out, list):
            out = out[min(self.visits[node["id"]], len(out) - 1)]
        self.visits[node["id"]] += 1
        return deepcopy(out)


class LLMRunner:
    """Live runner against any OpenAI-compatible endpoint (env-configured)."""

    def __init__(self):
        self.base = os.environ["AGR_LLM_BASE_URL"].rstrip("/")
        self.model = os.environ["AGR_LLM_MODEL"]
        self.key = os.environ.get("AGR_LLM_API_KEY", "")
        self.name = f"llm:{self.model}"

    def run(self, node: dict, bb: dict) -> dict:
        prompt = (
            f"You are node '{node['id']}' (speciality: {node['speciality']}) in a workflow. "
            f"Abilities: {', '.join(node.get('abilities', []))}. Blackboard: {json.dumps(bb, default=str)}. "
            "Reply with ONLY a JSON object of your output keys."
        )
        req = urllib.request.Request(
            f"{self.base}/chat/completions",
            data=json.dumps({"model": self.model,
                             "messages": [{"role": "user", "content": prompt}]}).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.key}"} if self.key else {})},
        )
        with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310
            text = json.load(r)["choices"][0]["message"]["content"]
        return json.loads(text[text.index("{"): text.rindex("}") + 1])


def run_graph(doc: dict, runner) -> RunReport:
    nodes = {n["id"]: n for n in doc["nodes"]}
    out_edges = defaultdict(list)
    has_incoming = set()
    for e in doc["edges"]:
        out_edges[e["from"]].append(e)
        has_incoming.add(e["to"])
    frontier = [n["id"] for n in doc["nodes"] if n["id"] not in has_incoming]
    bb: dict = {}
    rep = RunReport()
    cap = doc["termination"]["max_steps"]
    while frontier:
        if rep.steps >= cap:
            rep.hit_step_cap = True
            break
        nid = frontier.pop(0)
        rep.steps += 1
        rep.trace.append(nid)
        bb.update(runner.run(nodes[nid], bb))
        taken = [e for e in out_edges[nid] if edge_true(e.get("when"), bb)]
        if nodes[nid].get("kind") == "router" and taken:
            taken = taken[:1]
        for e in taken:
            if e["to"] not in frontier:
                frontier.append(e["to"])
    for v in doc.get("verification", []):
        if "command" in v:
            rep.skipped_commands += 1
            continue
        try:
            ok = bool(safe_eval(v["assert"], bb))
        except Exception as ex:
            ok, ex_note = False, f" ({type(ex).__name__}: {ex})"
        else:
            ex_note = ""
        if not ok:
            rep.assert_failures.append(v["assert"] + ex_note)
    return rep
