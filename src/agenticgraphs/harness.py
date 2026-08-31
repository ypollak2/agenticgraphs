"""M1 eval harness: execute AGR graphs against a runner and verify contracts.

The interpreter is real (routers, joins, bounded loops, verification asserts).
Runners are pluggable: MockRunner replays golden fixtures (measures graph/contract
mechanics), LLMRunner calls any OpenAI-compatible endpoint (measures model quality).
Every profile records which runner produced it — mock results are marked provisional.
"""
from __future__ import annotations

import json
import os
import random
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from . import shapes as _shapes
from .registry import ROOT as _REGISTRY_ROOT
from .safeexpr import UnsafeExpression, compile_expr

_ORDER = {"trivial": -1, "low": 0, "simple": 0, "medium": 1, "moderate": 1,
          "high": 2, "complex": 2, "critical": 3}


def _backoff(attempt: int) -> None:
    """Exponential backoff with jitter.

    The jitter matters when re-recording the registry: 83 graphs firing at one
    endpoint would otherwise retry in lockstep.
    """
    time.sleep(min(2 ** attempt, 8) * (0.5 + random.random()))  # noqa: S311 — backoff jitter, not a secret


class Level:
    """Ordered qualitative literal so conditions like `risk >= medium` evaluate."""

    def __init__(self, s: str):
        self.s, self.v = s, _ORDER[s]

    def _v(self, o):
        return o.v if isinstance(o, Level) else _ORDER.get(o)

    def __eq__(self, o):
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


class OutputView(DotDict):
    """`output.X` and a bare `X` on the blackboard are one fact, not two.

    The registry asserts on `output.violations` while nodes declare
    `outputs: [violations]` — two conventions for one contract, and the
    declaration is the one the model is told. So a model returns the fact flat,
    correctly, and an assert looking one level deeper misses it. Three separate
    patches at the prompt layer failed to route around that (see
    docs/plans/v7-audit.md); this resolves it where the two vocabularies actually
    meet, at evaluation.

    Precedence is deliberate: a key genuinely inside `output` wins, so a graph
    that nests properly is unaffected. The blackboard is only consulted for keys
    `output` does not carry.
    """

    def __init__(self, inner, blackboard):
        # Wrap on the way in: everything reached through `output` must keep
        # attribute access, or `all(f.file for f in output.findings)` breaks on
        # the plain dicts a fixture supplies.
        super().__init__(wrap(inner) if isinstance(inner, dict) else {})
        self._bb = blackboard

    def __getattr__(self, k):
        if k == "_bb":
            raise AttributeError(k)
        try:
            return self[k]
        except KeyError:
            pass
        if k in self._bb:
            return wrap(self._bb[k])
        raise AttributeError(k)


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
    """Evaluate a graph expression against the blackboard.

    Two defences, and the first one is the one that matters. `compile_expr`
    refuses any construct outside the allowlist, so `().__class__.__bases__` —
    the escape every `{"__builtins__": {}}` sandbox has — never compiles. The
    closed namespace then decides what the surviving expression can see.

    Raising rather than returning False is deliberate: an expression this
    rejects is a hostile or malformed graph, and `edge_true` catching it into a
    silently-untaken edge would let a rejected graph run to a plausible-looking
    verdict. Callers that must not fail closed catch UnsafeExpression by name.
    """
    code = compile_expr(expr)
    ns = {**_SAFE, **wrap(dict(bb))}
    # `output` is the one name whose lookup falls through to the blackboard.
    ns["output"] = OutputView(bb.get("output"), dict(bb))
    # The namespace is passed as GLOBALS, not locals, and the difference is not
    # stylistic. A comprehension body is its own scope that sees globals and its
    # own bindings — never the enclosing locals — so with `eval(code, g, ns)` a
    # nested quantifier such as
    #     all(all(c in output.grid for c in r.criteria) for r in output.matrix)
    # raised `NameError: name 'all' is not defined` from the inner scope. Single
    # comprehensions survived only because their outermost iterable is evaluated
    # eagerly in the enclosing scope, which is why this went unnoticed while
    # every assert in the registry was one level deep.
    ns["__builtins__"] = {}
    return eval(code, ns)  # noqa: S307 — allowlisted expression, closed namespace


def edge_true(when: str | None, bb: dict) -> bool:
    if not when:
        return True
    try:
        return bool(safe_eval(when, bb))
    except UnsafeExpression:
        raise  # a refused expression is a bad graph, not an untaken edge
    except Exception:
        return False  # unresolvable condition = edge not taken


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
#: Models routinely emit Python literals inside otherwise-valid JSON. Normalising
#: them is tolerance for a known quirk, not papering over a wrong answer — the
#: keys and values are exactly what the model meant.
_PY_LITERAL = re.compile(r"(?<![\w\"])(True|False|None)(?![\w\"])")
_PY_MAP = {"True": "true", "False": "false", "None": "null"}


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a model reply, tolerantly.

    The original was one line — `text[text.index("{"):text.rindex("}")+1]` — and a
    multi-model sweep showed why that matters: a large share of apparent *model*
    failures were markdown fences, trailing commas, or prose wrapped around
    otherwise-correct JSON. Counting harness brittleness as a model failure would
    misattribute exactly the thing the sweep exists to measure.

    Raises ValueError when there is genuinely no object to find, so a real
    failure is still a failure.
    """
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in model reply: {text[:120]!r}")
    blob = text[start:end + 1]
    repaired = _PY_LITERAL.sub(lambda m: _PY_MAP[m.group(1)], _TRAILING_COMMA.sub(r"\1", blob))
    for candidate in (blob, _TRAILING_COMMA.sub(r"\1", blob), repaired):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    # Last resort: the largest balanced prefix, for a reply truncated mid-object.
    depth = 0
    for i, ch in enumerate(blob):
        depth += (ch == "{") - (ch == "}")
        if depth == 0 and i:
            try:
                return json.loads(blob[: i + 1])
            except json.JSONDecodeError:
                break
    raise ValueError(f"unparseable JSON in model reply: {blob[:120]!r}")


def _asserted_keys(expr: str) -> set[str]:
    """Local import shim — `validate` imports `subgraphs`, which imports nothing here."""
    from .validate import asserted_keys

    return asserted_keys(expr)


class HumanGateRequired(Exception):
    """A `kind: human` node was reached with no authority to approve it.

    Raised by LLMRunner: a model must not sign its own approval gate. Pass
    auto_approve=True (CI only) to bypass — the report is stamped accordingly
    and the resulting profile is not authoritative.
    """


@dataclass
class RunReport:
    trace: list[str] = field(default_factory=list)
    steps: int = 0
    assert_failures: list[str] = field(default_factory=list)
    skipped_commands: int = 0
    commands_run: int = 0
    command_failures: list[str] = field(default_factory=list)
    hit_step_cap: bool = False
    # v1.1
    deadlocked: bool = False
    auto_approved: bool = False
    approvals: list[tuple[str, bool]] = field(default_factory=list)
    retries_used: int = 0
    expanded: bool = False
    # v1.2 — execution history. A frame is what ONE node execution wrote, not a
    # copy of the board: cheap enough to keep for every step, and the substrate
    # phase-scoped verification, fan-out and reflexion memory all read from.
    frames: list[dict] = field(default_factory=list)
    assembled: list[str] = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    shape_violations: list[str] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        """Report whether any claim in this run traces to a real tool call.

        The distinction `assert-grounded` rests on: an assert that held because a
        command exited 0 is evidence; the same assert holding because a model said
        so is not.
        """
        return any(c.ok for c in self.tool_calls)
    lessons: list[dict] = field(default_factory=list)
    budget_exhausted: str = ""
    #: Real token counts and priced cost when the runner supplied them.
    #: Absent on a mock run, which is how a reader tells the two apart.
    usage: dict = field(default_factory=dict)
    journal: list[dict] = field(default_factory=list)
    resumed_nodes: list[str] = field(default_factory=list)
    state_violations: list[str] = field(default_factory=list)
    truncations: list[str] = field(default_factory=list)
    searches: list[dict] = field(default_factory=list)
    # v1.6 — the graph declared `goal.required` and no goal was supplied, so it
    # refused rather than inventing a subject. Carries the graph's own
    # `goal.description`, which is what the refusal tells the caller to bring.
    goal_missing: str = ""

    def frames_for(self, node_id: str) -> list[dict]:
        return [f for f in self.frames if f["node"] == node_id]

    def phase_frame(self, phase: str) -> dict:
        """The blackboard state a phase produced, as its child graph would see it.

        Every write made inside the phase, merged in execution order. Not just
        the last one: run standalone, a child graph ends with a blackboard that
        *accumulated* across its nodes, and its asserts were written against
        that. `postmortem-writer` writes `output` in `produce` and then runs
        `review` — taking only the final write would lose the very key the
        child's contract asserts on.
        """
        merged: dict = {}
        for f in self.frames:
            if not (f["node"] == phase or f["node"].startswith(phase + ".")):
                continue
            for k, v in f["out"].items():
                # `output` is an accumulator, not a slot. Last-write-wins lost any
                # fact established mid-phase whenever a later node in the same
                # phase wrote its own `output` — which undid the v1.6 reconcile
                # node-by-node and is why that fix measured as no change at all.
                if k == "output" and isinstance(merged.get(k), dict):
                    if isinstance(v, dict):
                        merged[k] = {**merged[k], **v}
                    continue  # a scalar never displaces facts already gathered
                merged[k] = v
        return merged

    @property
    def rejected_approvals(self) -> list[str]:
        return [nid for nid, ok in self.approvals if not ok]

    @property
    def passed(self) -> bool:
        return (not self.assert_failures and not self.command_failures
                and not self.state_violations and not self.budget_exhausted
                and not self.shape_violations and not self.goal_missing
                and not self.hit_step_cap and not self.deadlocked)


def _goal_line(bb: dict) -> str:
    """Surface the run's goal on its own line.

    It is already inside the serialised blackboard, so this is redundant to a
    careful reader. Models are not careful readers: v1.6 and v1.7 each measured a
    fact that was present, buried, and consequently ignored. A goal the node does
    not act on is the same as no goal.
    """
    goal = bb.get("goal")
    return f"Your goal for this run: {goal}\n" if goal else ""


class MockRunner:
    """Replays per-node fixture outputs; a list means successive visits."""

    name = "mock"

    def __init__(self, node_outputs: dict):
        self.node_outputs = node_outputs
        self.visits: defaultdict[str, int] = defaultdict(int)

    def run(self, node: dict, bb: dict) -> dict:
        out = self.node_outputs.get(node["id"], {})
        if isinstance(out, list):
            out = out[min(self.visits[node["id"]], len(out) - 1)]
        self.visits[node["id"]] += 1
        return deepcopy(out)


class LLMRunner:
    """Live runner against any OpenAI-compatible endpoint (env-configured)."""

    #: Sampling is pinned, not left to the provider. The registry's own variance
    #: analysis reports 50 of 83 graphs where one model both passed and failed
    #: across samples — under a provider-default temperature, an unknown share of
    #: that is sampling noise being attributed to the graph. A seed and t=0 make
    #: a recording a fact about the model instead of a draw from it.
    SAMPLING = {"temperature": 0, "seed": 7, "max_tokens": 2048}

    #: Retries exist so a 429 is not recorded as a contract failure. A rate limit
    #: says nothing about whether the graph works, and a registry that cannot tell
    #: those apart publishes the difference as quality.
    RETRY_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
    MAX_ATTEMPTS = 4

    def __init__(self):
        self.base = os.environ["AGR_LLM_BASE_URL"].rstrip("/")
        # Checked once, here, so every `urlopen` below can state why it is safe.
        # `file:` and custom schemes are exactly what S310 warns about, and an
        # endpoint URL is operator config that no graph can influence.
        if not self.base.startswith(("http://", "https://")):
            raise ValueError(f"AGR_LLM_BASE_URL must be http(s), got {self.base!r}")
        self.model = os.environ["AGR_LLM_MODEL"]
        self.key = os.environ.get("AGR_LLM_API_KEY", "")
        self.name = f"llm:{self.model}"
        #: Real token counts, accumulated across every call this runner makes.
        #: `_EST_USD_PER_NODE` used to stand in for this with a hardcoded 0.002 —
        #: a number that could halt a run on `budget.usd_max` while bearing no
        #: relation to what the run cost. Every OpenAI-compatible response
        #: carries `usage`; it was being read and discarded.
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    def _post(self, payload: dict) -> dict:
        """One chat completion: pinned sampling, retried transport, counted usage.

        Every live call in this module goes through here so that determinism,
        backoff, and accounting cannot drift apart between the plain runner and
        the tool-using one.
        """
        payload = {**self.SAMPLING, **payload}
        data = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json",
                   **({"Authorization": f"Bearer {self.key}"} if self.key else {})}
        last: Exception | None = None
        for attempt in range(self.MAX_ATTEMPTS):
            req = urllib.request.Request(  # noqa: S310 — base URL validated as http(s) in __init__
                f"{self.base}/chat/completions", data=data, headers=headers)
            try:
                # S310: the base URL is operator config validated as http(s) in
                # __init__, and no graph can influence it.
                with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
                    body = json.load(r)
            except urllib.error.HTTPError as ex:
                last = ex
                if ex.code == 400 and "response_format" in str(payload):
                    # Not every OpenAI-compatible endpoint implements JSON mode.
                    # Dropping it is a capability fallback, not a retry: the
                    # `extract_json` repair layer covers what it costs us.
                    payload.pop("response_format", None)
                    data = json.dumps(payload).encode()
                    continue
                if ex.code not in self.RETRY_STATUS:
                    raise
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as ex:
                last = ex
            else:
                u = body.get("usage") or {}
                self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
                self.usage["completion_tokens"] += u.get("completion_tokens", 0)
                self.usage["calls"] += 1
                return body
            _backoff(attempt)
        raise RuntimeError(
            f"{self.MAX_ATTEMPTS} attempts to {self.base} failed; last: {last!r}"
        )

    def contract_for(self, node: dict) -> dict:
        """The slice of the contract this node is actually responsible for.

        `bind` used to collect every assert in the expanded graph and hand the
        same set to every node. In a composite that meant a node *inside* a phase
        was told to produce the parent graph's final answer — and 16 of 46 child
        nodes across the recordings duly did, one of them returning the parent's
        assert *strings* as a value.

        A node `<phase>.<child>` gets the entries tagged `phase: <phase>`; an
        unprefixed node gets the untagged ones. If that leaves nothing the node
        gets nothing, because silence is better than a misleading instruction.
        """
        phase = node["id"].split(".")[0] if "." in node["id"] else None
        checks = [
            v["assert"] for v in self.verification
            if "assert" in v and v.get("phase") == phase
        ]
        keys: set[str] = set()
        for check in checks:
            keys |= _asserted_keys(check)
        return {"checks": checks, "keys": keys}

    def _assembly_hint(self, declared: list[str], keys: set[str]) -> str:
        """Tell a node that assembles `output` where its contents come from.

        v1.3 declared the asserted sub-keys on the terminal node and re-recorded;
        0 of 12 runs passed. `output` is assembled from facts *upstream* nodes
        established, so "return these keys" asks the terminal to invent values it
        never computed. v1.4 declares each fact on the node that produces it and
        tells the assembler to read them off the blackboard it can already see.
        """
        if "output" not in declared or not keys:
            return ""
        return (
            f"The `output` object must contain: {json.dumps(sorted(keys))}. "
            "Take each value from the blackboard above — do not invent them. "
        )

    def bind(self, doc: dict) -> None:
        """Give the runner the graph's contract before execution starts.

        Without this the prompt asked for "your output keys" without ever saying
        which — so a real model returned plausible-looking JSON with entirely
        different key names and every contract assert failed on AttributeError.
        v1.1 added declared `outputs` per node and the live runner never used them.
        """
        self.contract = doc.get("termination", {}).get("contract", "")
        # Kept whole: which entries apply is a per-node question, answered by
        # `contract_for` at run time rather than flattened here.
        self.verification = list(doc.get("verification") or [])
        self.checks = [v["assert"] for v in self.verification if "assert" in v]
        self.asserted: set[str] = set()
        for check in self.checks:
            self.asserted |= _asserted_keys(check)

    def run(self, node: dict, bb: dict) -> dict:
        declared = _shapes.names(node)
        # "Return the keys this step is responsible for" is a question about the
        # node's JOB, and models answer it as one: `position-a` in
        # `ab-test-analysis` replied {"keys": ["recomputed_effect",
        # "claimed_effect"]} — naming keys instead of producing values, starving
        # everything downstream. v1.5 declares outputs on every dependent node so
        # the first branch is what actually runs; the fallback must still ask for
        # values rather than for a description of the work.
        wants = (
            f"You MUST return exactly these keys, with concrete values: {json.dumps(declared)}. "
            if declared else
            "Return a JSON object of the concrete values this step produces. "
        )
        wants += (
            "Return values, never key names, plans, or descriptions of what you would do. "
        )
        # The graph's termination contract is the *parent's* summary of the whole
        # workflow. Handing it to a node inside a phase gave the model a second
        # vocabulary to drift into — one recording returned prose beginning "The
        # exit contract stating that..." where an object was required. A child
        # node is told its phase's asserts and nothing else.
        contract = "" if "." in node["id"] else getattr(self, "contract", "")
        scoped = self.contract_for(node) if hasattr(self, "verification") else {
            "checks": getattr(self, "checks", []), "keys": getattr(self, "asserted", set())
        }
        # v1.8 — the assert TEXT no longer reaches the model. Handing a node
        # `["output.matches_ownership_map"]` and then scoring it on
        # `output.matches_ownership_map` measures whether a model can echo a flag
        # it was just shown, not whether the workflow works: 31 of 117 asserts in
        # the registry are a bare truthy read, and for 6 of them the key is
        # declared as an output of the graph's own verifier. Every pass rate
        # recorded before this change was contaminated by it.
        #
        # What survives is the *keys* (via `_assembly_hint`) and the exit
        # contract — a node is entitled to know what it must produce and what the
        # workflow is for. It is not entitled to the marking scheme.
        # v1.8 — `criteria` is what replaces the assert text T7 removed, and the
        # difference is the whole point. An assert is the marking scheme: telling
        # a node `output.matches_ownership_map` and then scoring it on that key
        # measures echo. Criteria are the rubric: what "matches the ownership map"
        # MEANS in this domain, which is the thing a verifier has to reason about
        # and the thing that made two identically-shaped graphs different graphs.
        criteria = node.get("criteria", "")
        prompt = (
            f"You are node '{node['id']}' (speciality: {node['speciality']}) in a workflow. "
            f"Abilities: {', '.join(node.get('abilities', []))}.\n"
            + _goal_line(bb)
            + f"Blackboard so far: {json.dumps(bb, default=str)}\n"
            + (f"The workflow's exit contract is: {contract}\n" if contract else "")
            + (f"What this step must judge: {criteria}\n" if criteria else "")
            + wants
            + _shapes.describe(node)
            + self._assembly_hint(declared, scoped["keys"])
            + "Reply with ONLY a JSON object. No prose, no markdown fence."
        )
        body = self._post({"model": self.model,
                           "messages": [{"role": "user", "content": prompt}],
                           "response_format": {"type": "json_object"}})
        return extract_json(body["choices"][0]["message"]["content"])

    def approve(self, node: dict, bb: dict, auto_approve: bool = False) -> dict:
        """Refuse to sign a human gate — a model must not approve its own work.

        `auto_approve` exists for CI only; the run report is stamped
        `auto_approved` so the resulting profile is never mistaken for a real
        sign-off.
        """
        if not auto_approve:
            raise HumanGateRequired(
                f"node '{node['id']}' is a human approval gate "
                f"(contract: {node['approval']['contract']}). "
                "Re-run with --auto-approve to bypass in CI, or supply an approving runner."
            )
        return {"signed_off": True, "approver": "auto-approve", "auto_approved": True}


class ReplayRunner:
    """Replays *recorded real-model* outputs from a graph's live/<case>.json.

    The depth grading shipped in v1.1 could report `assert-live`, but nothing
    ever produced it: a live run needs a network call, so CI never made one and
    every graph stayed at `assert-fixture`. A recording is a real model's output,
    captured once and checked in, so the assert is graded against what a model
    actually said rather than what a fixture author wished it would say.

    Each recording stamps the model and date it came from; the scoreboard shows
    the age, because a recording is evidence with a shelf life.
    """

    def __init__(self, recording: dict):
        self.model = recording.get("model", "unknown")
        self.recorded = recording.get("recorded", "unknown")
        # Replayed so the grade survives: a recording of a grounded run must
        # still read as grounded.
        self.recorded_tool_calls = recording.get("tool_calls") or []
        self.node_outputs = recording["node_outputs"]
        self.visits: dict = defaultdict(int)
        self.name = f"llm-replay:{self.model}"

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def run(self, node: dict, bb: dict) -> dict:
        out = self.node_outputs.get(node["id"], {})
        if isinstance(out, list):
            out = out[min(self.visits[node["id"]], len(out) - 1)]
        self.visits[node["id"]] += 1
        return deepcopy(out)

    def approve(self, node: dict, bb: dict, auto_approve: bool = False) -> dict:
        """A recording cannot contain a human signature — refuse like LLMRunner."""
        if not auto_approve:
            raise HumanGateRequired(
                f"node '{node['id']}' is a human approval gate; a replayed model "
                "recording is not a sign-off"
            )
        return {"signed_off": True, "approver": "auto-approve", "auto_approved": True}


class ToolRunner(LLMRunner):
    """LLMRunner plus the abilities each node declares, actually bound.

    Only a node's own `abilities` are offered — never a general toolbox. The
    registry's premise is that what a node may do is written down, and handing a
    model an open set of tools would discard exactly that property.

    Mutating abilities (`risk: write`/`execute`) stay unbound unless the caller
    opts in, reusing the risk level `abilities/*.yaml` has declared since M0
    rather than inventing a second permission model.
    """

    MAX_TOOL_ROUNDS = 4

    def __init__(self, root=None, allow_mutating: bool = False, report=None,
                 registry_root=None):
        """`root` is where commands run; `registry_root` is where abilities live.

        These were one attribute, and the natural use — point the runner at the
        repository you want it to work on — silently broke ability lookup: the
        registry was searched under the target checkout, `available()` found no
        `abilities/*.yaml`, `bind_for` returned nothing, and every node quietly
        degraded to the ungrounded runner. No error, just a run whose asserts all
        became model claims again. They are two different roots and now say so.
        """
        super().__init__()
        self.root = Path(root) if root else Path.cwd()
        self.registry_root = Path(registry_root) if registry_root else _REGISTRY_ROOT
        self.allow_mutating = allow_mutating
        self.report = report
        self.name = f"tools:{self.model}"

    def _chat(self, messages: list, tools: list) -> dict:
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        return self._post(payload)["choices"][0]["message"]

    def run(self, node: dict, bb: dict) -> dict:
        from . import bindings

        bound = bindings.bind_for(node, self.allow_mutating, self.registry_root)
        if not bound:
            return super().run(node, bb)  # nothing to ground; behave as before

        messages = [{"role": "user", "content": self._prompt_text(node, bb, bound)}]
        tools = bindings.as_openai_tools(bound)

        for _ in range(self.MAX_TOOL_ROUNDS):
            msg = self._chat(messages, tools)
            calls = msg.get("tool_calls") or []
            if not calls:
                return extract_json(msg.get("content") or "")
            messages.append(msg)
            for call in calls:
                fn = call["function"]
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                rec = bindings.invoke(fn["name"], args, self.root,
                                      self.allow_mutating, self.registry_root)
                if self.report is not None:
                    self.report.tool_calls.append(rec)
                messages.append({
                    "role": "tool", "tool_call_id": call["id"],
                    "content": json.dumps(rec.evidence if rec.ok else {"error": rec.detail},
                                          default=str)[:4000],
                })
        # Out of rounds: ask once more, without tools, for the final object.
        messages.append({"role": "user",
                         "content": "Now return ONLY the JSON object, using the tool "
                                    "results above. Do not call further tools."})
        return extract_json(self._chat(messages, [])["content"] or "")

    def _prompt_text(self, node: dict, bb: dict, bound: dict) -> str:
        declared = _shapes.names(node)
        scoped = self.contract_for(node)
        names = ", ".join(sorted(bound))
        return (
            f"You are node '{node['id']}' (speciality: {node['speciality']}) in a workflow.\n"
            + _goal_line(bb)
            + f"Blackboard so far: {json.dumps(bb, default=str)}\n"
            # The tool-using path leaked the same assert text the plain runner did —
            # and leaks it to the node best equipped to fabricate a matching fact,
            # since this one can also cite a tool result. Criteria replace it.
            + (f"What this step must judge: {node['criteria']}\n"
               if node.get("criteria") else "")
            + f"You have these tools and MUST use them for any fact you cannot "
              f"otherwise verify: {names}. Never invent a URL, exit code, file, line "
              f"number or identifier — obtain it from a tool.\n"
            + (f"You MUST return exactly these keys, with concrete values: "
               f"{json.dumps(declared)}. " if declared else "")
            + self._assembly_hint(declared, scoped["keys"])
            + "When done, reply with ONLY a JSON object. No prose, no markdown fence."
        )


def _normalize(doc: dict) -> dict:
    """Desugar v1.1 `on_error: <node>` into an explicit error edge."""
    extra = [
        {"from": n["id"], "to": n["on_error"], "kind": "error"}
        for n in doc["nodes"]
        if n.get("on_error")
    ]
    if not extra:
        return doc
    out = dict(doc)
    out["edges"] = list(doc["edges"]) + extra
    return out


def _quorum_n(join: str) -> int | None:
    if join.startswith("quorum(") and join.endswith(")"):
        return int(join[7:-1])
    return None


class _Readiness:
    """Evaluates join rules against edge resolution and dead-branch settlement.

    Only *forward flow* edges count toward a join. Back-edges (retry loops) and
    compensate edges are excluded — a retry edge is by construction unresolved
    on the first pass, so counting it would deadlock every `all` join.

    The subtle case is a predecessor that will never run: when a router picks
    one branch, the other branch's node never executes, so its outgoing edge
    never *resolves*. A naive `all` would wait forever. Such an edge is instead
    **settled**: its source is provably dead (not queued, never ran, and every
    one of its own incoming edges settled without being taken). Settlement
    recurses up the graph, with a visit guard for cycles.
    """

    def __init__(self, doc, nodes, in_flow, resolved, taken, ran, pending, forced):
        self.edges, self.nodes, self.in_flow = doc["edges"], nodes, in_flow
        self.resolved, self.taken, self.ran, self.pending = resolved, taken, ran, pending
        # Nodes pulled in by a taken error/compensate edge. These are off the
        # forward-flow graph entirely, so no join rule can vouch for them —
        # being routed to by an exceptional path IS their readiness condition.
        self.forced = forced

    def _dead(self, nid: str, seen: frozenset) -> bool:
        if nid in self.ran or nid in self.pending or nid in seen:
            return False
        incoming = self.in_flow.get(nid, [])
        if not incoming:
            return False  # an entry node that simply hasn't been reached yet
        seen = seen | {nid}
        return all(self.settled(i, seen) for i in incoming) and not any(
            i in self.taken for i in incoming
        )

    def settled(self, i: int, seen: frozenset = frozenset()) -> bool:
        """Edge i will never change state: its source ran, or can never run."""
        return i in self.resolved or self._dead(self.edges[i]["from"], seen)

    def ready(self, nid: str) -> bool:
        if nid in self.forced:
            return True
        incoming = self.in_flow.get(nid, [])
        if not incoming:
            return True  # entry node
        join = self.nodes[nid].get("join", "any")
        n_taken = sum(1 for i in incoming if i in self.taken)
        if join == "all":
            return all(self.settled(i) for i in incoming) and n_taken >= 1
        q = _quorum_n(join)
        if q is not None:
            return n_taken >= q
        return n_taken >= 1  # "any" — v1 behavior


#: `{key}` in a command is filled from the blackboard. Some checks are only the
#: caller's to name — `verifier-swarm` exists to run whatever command proves the
#: caller's goal done — and before this the graph expressed that as the literal
#: string "user-supplied verify command must exit 0", which `shlex.split` would
#: have tried to execute as the program `user-supplied`. A placeholder makes the
#: same intent runnable, and `_lint_commands` refuses prose.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z_0-9]*)\}")


def resolve_command(cmd: str, bb: dict) -> str:
    """Fill `{key}` placeholders from the blackboard.

    A placeholder with no value raises rather than running a half-substituted
    command: `pytest {suite}` with no `suite` would otherwise run the whole
    suite and report a pass for a check that never happened.
    """
    missing = [m.group(1) for m in _PLACEHOLDER.finditer(cmd) if m.group(1) not in bb]
    if missing:
        raise KeyError(f"command needs {missing} which the blackboard does not supply")
    return _PLACEHOLDER.sub(lambda m: str(bb[m.group(1)]), cmd)


def _run_command(cmd: str, cwd, rep: RunReport, bb: dict | None = None) -> None:
    """Execute a `verification[].command` and record its exit status.

    Opt-in only. A verification command runs real code on the real machine, so
    the default stays `skipped` — counted and reported, never silently treated
    as passing.
    """
    try:
        cmd = resolve_command(cmd, bb or {})
    except KeyError as ex:
        rep.command_failures.append(f"{cmd} ({ex})")
        return
    try:
        proc = subprocess.run(  # noqa: S603 — command is authored in the graph, opt-in by the caller
            shlex.split(cmd), cwd=cwd, capture_output=True, text=True, timeout=300, check=False
        )
    except (OSError, subprocess.SubprocessError) as ex:
        rep.command_failures.append(f"{cmd} ({type(ex).__name__}: {ex})")
        return
    rep.commands_run += 1
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        rep.command_failures.append(f"{cmd} (exit {proc.returncode}: {tail[0]})")


#: USD per 1M tokens, (prompt, completion). Live runs price from the `usage` the
#: endpoint returns, so `budget.usd_max` halts on what the run actually cost.
#: An unlisted model falls back to `_EST_USD_PER_NODE` and the report says so —
#: a guessed price must be labelled as one, never averaged in beside a measured one.
_TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}

#: Fallback for a mock run or an unpriced model: there are no token counts to
#: price, so the cap needs *something* to enforce against. Deliberately crude and
#: deliberately not presented as a price — a cap that is recorded and ignored is
#: the pattern v1.3 exists to stop repeating.
_EST_USD_PER_NODE = 0.002


def _spend(runner, steps: int) -> tuple[float, bool]:
    """(cost so far, whether it was measured). Measured beats estimated, always."""
    usage = getattr(runner, "usage", None)
    if not usage or not usage.get("calls"):
        return steps * _EST_USD_PER_NODE, False
    model = getattr(runner, "model", "")
    price = _TOKEN_PRICES.get(model) or _TOKEN_PRICES.get(model.split(":")[0])
    if price is None:
        return steps * _EST_USD_PER_NODE, False
    return (usage["prompt_tokens"] * price[0] + usage["completion_tokens"] * price[1]) / 1e6, True


def run_graph(doc: dict, runner, root=None, auto_approve: bool = False,
              run_commands: bool = False, resume_from=None,
              inputs: dict | None = None) -> RunReport:
    """Execute an AGR graph against a runner.

    v1.1 adds: subgraph expansion, join semantics, error/compensate edge kinds,
    per-node retries, and human approval gates. With every node defaulting to
    `join: any` and no v1.1 fields present, scheduling is byte-identical to v1 —
    locked by tests/fixtures/v1_trace_lock.json.

    v1.6 adds `inputs`: the blackboard keys a caller supplies at entry. 31 graphs
    have declared `state.inputs` since v1.1 and the runtime seeded none of them —
    the linter vouched for values that never arrived, so every graph began work
    without knowing its subject. `inputs` is that missing half, and `goal` is the
    key it exists for. Passing nothing reproduces pre-v1.6 behaviour exactly.
    """
    from .subgraphs import entry_nodes, expand, has_subgraphs  # local: avoids an import cycle

    rep = RunReport()
    seed = dict(inputs or {})
    # The goal gate runs before anything is scheduled. A graph that cannot know
    # what it is working on does not guess at it: it refuses, having executed no
    # node, and reports what it needed. `supplied_by_trigger` exempts graphs whose
    # firing event carries the subject — the requirement is on manual invocation.
    goal = doc.get("goal") or {}
    if (goal.get("required") and not seed.get("goal")
            and not (goal.get("supplied_by_trigger") and doc.get("triggers"))):
            # Deliberately NOT written to `rep.trace`: that field means "nodes that
            # executed", and callers compare it against node ids (the adapter parity
            # test does exactly this). A refusal executed nothing, so the trace stays
            # empty and `goal_missing` carries the reason — the same shape as
            # `deadlocked` and `budget_exhausted`.
            rep.goal_missing = goal.get("description") or "a goal for this run"
            return rep
    if hasattr(runner, "bind"):
        runner.bind(doc)
    # Give a tool-bound runner the report to append its calls to, unwrapping a
    # recording wrapper. Without this the calls happen and leave no trace, which
    # is the same failure as not making them.
    for candidate in (runner, getattr(runner, "inner", None)):
        if candidate is not None and hasattr(candidate, "allow_mutating"):
            candidate.report = rep
    for rec in getattr(runner, "recorded_tool_calls", []):
        from .bindings import ToolCall

        rep.tool_calls.append(
            ToolCall(rec["ability"], rec.get("args", {}), rec["ok"], rec.get("detail", ""))
        )
    if has_subgraphs(doc):
        doc = expand(doc, root) if root else expand(doc)
        rep.expanded = True
    doc = _normalize(doc)

    nodes = {n["id"]: n for n in doc["nodes"]}
    order = {n["id"]: i for i, n in enumerate(doc["nodes"])}
    out_edges: dict[str, list[int]] = defaultdict(list)
    in_flow: dict[str, list[int]] = defaultdict(list)
    for i, e in enumerate(doc["edges"]):
        out_edges[e["from"]].append(i)
        kind = e.get("kind", "flow")
        is_back = order.get(e["to"], 0) <= order.get(e["from"], -1)
        if kind == "flow" and not is_back:
            in_flow[e["to"]].append(i)

    # One shared definition of "entry" across harness, linter and compose.
    # Conditionally-reached nodes land in the initial frontier but are gated by
    # their join rule, so a branch the router did not pick never executes.
    pending = list(entry_nodes(doc))

    resolved: set[int] = set()
    taken: set[int] = set()
    ran: set[str] = set()
    forced: set[str] = set()
    visits: dict[str, int] = defaultdict(int)
    attempts: dict[str, int] = defaultdict(int)
    bb: dict = seed
    cap = doc["termination"]["max_steps"]
    budget = doc.get("budget") or {}
    # D3: resume is replay. v1.2 already journals every node execution, so a
    # killed run is resumed by replaying its frames and skipping what completed —
    # no new state model, no storage engine.
    completed: dict[str, dict] = {}
    if resume_from:
        for line in Path(resume_from).read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                completed[entry["node"]] = entry["out"]
    rdy = _Readiness(doc, nodes, in_flow, resolved, taken, ran, pending, forced)

    while pending:
        if rep.steps >= cap:
            rep.hit_step_cap = True
            break
        # Budgets are checked *before* the node runs, not after it is recorded:
        # a cap that lets the step it forbids execute first is not a cap.
        if budget.get("steps_max") and rep.steps >= budget["steps_max"]:
            rep.budget_exhausted = (
                f"steps_max={budget['steps_max']} reached; halted before step {rep.steps + 1}"
            )
            break
        if budget.get("usd_max"):
            spent, measured = _spend(runner, rep.steps + 1)
            if spent > budget["usd_max"]:
                how = "measured" if measured else "estimated"
                rep.budget_exhausted = (
                    f"usd_max=${budget['usd_max']:.4f} would be exceeded by step "
                    f"{rep.steps + 1} ({how} ${spent:.4f})"
                )
                break
        pick = next((i for i, nid in enumerate(pending) if rdy.ready(nid)), None)
        if pick is None:
            # Nothing is ready. Distinguish two cases: a node whose incoming
            # edges are all settled but unsatisfying is a *dead branch* (the
            # router chose elsewhere) and is simply dropped; a node still
            # waiting on something that could still happen is a real deadlock.
            #
            # Settlement must be evaluated with the queue drained. A queued node
            # is never "dead", so asking `is X dead?` while X is still queued is
            # circular: two unready siblings would each keep the other alive and
            # report a deadlock that does not exist.
            survivors = list(pending)
            pending.clear()
            stuck = [
                nid for nid in survivors
                if any(not rdy.settled(i) for i in in_flow.get(nid, []))
            ]
            if stuck:
                pending.extend(survivors)
                rep.deadlocked = True
            break
        nid = pending.pop(pick)
        node = nodes[nid]
        rep.steps += 1
        rep.trace.append(nid)
        ran.add(nid)
        forced.discard(nid)

        # `attempts` is owned by the runtime, not by node output. 48 edge guards
        # across the registry read it (`verify_failed and attempts < 3`) and
        # nothing produced it: `edge_true` swallowed the NameError and returned
        # False, so every bounded retry loop silently failed closed unless a
        # fixture happened to supply the value. Publish the visit count — 1 on
        # the first execution — before the node runs, so guards evaluated after
        # it see the attempt that just happened.
        visits[nid] += 1
        bb["attempts"] = visits[nid]

        _aggregate(node, bb)
        if nid in completed and visits[nid] == 1:
            out = completed.pop(nid)
            rep.resumed_nodes.append(nid)
            rep.frames.append({"node": nid, "visit": 1, "out": out, "resumed": True})
            bb.update(out)
            _fire(nid, node, out, doc, out_edges, resolved, taken, forced, pending, bb, rep)
            continue
        if node.get("kind") == "human":
            out = _run_gate(node, bb, runner, auto_approve, rep)
        elif node.get("fan_out"):
            out = _fan_out(node, bb, runner, rep, visits[nid])
        elif node.get("kind") == "search":
            out = _search(node, bb, runner, rep, visits[nid])
        else:
            before = len(rep.tool_calls)
            out = _reconcile_output(node, runner.run(node, bb), runner, rep)
            _bind_evidence(bb, rep, before)
            rep.frames.append({"node": nid, "visit": visits[nid], "out": out})
        bb.update(out)
        violations = _shapes.violations(node, out)
        if violations:
            rep.shape_violations += violations

        errored = bool(out.get("error"))
        if errored and attempts[nid] < node.get("retries", {}).get("max", 0):
            attempts[nid] += 1
            rep.retries_used += 1
            pending.insert(0, nid)  # retry before draining the rest of the frontier
            continue

        _fire(nid, node, out, doc, out_edges, resolved, taken, forced, pending, bb, rep)

    if (doc.get("durability") or {}).get("checkpoint") == "every_node":
        rep.journal = [{"node": f["node"], "out": f["out"]}
                       for f in rep.frames if not f.get("resumed")]

    _check_state(doc, bb, root, rep)
    _persist_memory(doc, bb, root, rep)

    for v in doc.get("verification", []):
        if "command" in v:
            if run_commands:
                _run_command(v["command"], root, rep, bb)
            else:
                rep.skipped_commands += 1
            continue
        if "assert" not in v:
            continue  # describe-only: prose, graded as unverified by evalcmd
        # A phase-tagged assert came from a subgraph child and only ever held at
        # the instant that phase's terminal ran. Evaluating it against the final
        # blackboard — which a later phase has since overwritten — is why v1.1
        # dropped child verification entirely.
        scope = {**bb, **rep.phase_frame(v["phase"])} if v.get("phase") else bb
        try:
            ok = bool(safe_eval(v["assert"], scope))
        except UnsafeExpression:
            # A refused expression is a rejected graph. Recording it as one more
            # failed assert would let a hostile contribution read as merely a
            # low-scoring one, which is exactly the signal that must not blend in.
            raise
        except Exception as ex:
            ok, ex_note = False, f" ({type(ex).__name__}: {ex})"
        else:
            ex_note = ""
        if not ok:
            label = f"[{v['phase']}] " if v.get("phase") else ""
            rep.assert_failures.append(label + v["assert"] + ex_note)
    usage = getattr(runner, "usage", None)
    if usage and usage.get("calls"):
        spent, measured = _spend(runner, rep.steps)
        rep.usage = {**usage, "usd": round(spent, 6), "usd_measured": measured}
    return rep


_AGG = {
    "union": lambda vs: [x for v in vs for x in (v if isinstance(v, list) else [v])],
    "median": lambda vs: sorted(vs)[len(vs) // 2] if vs else None,
    "best": lambda vs: max(vs) if vs else None,
}


def _majority(values: list):
    """Most common value, or None on a tie — a tie is a real signal, not noise."""
    counts: dict = defaultdict(int)
    for v in values:
        counts[json.dumps(v, sort_keys=True, default=str)] += 1
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return json.loads(ranked[0][0])


_AGG["majority"] = _majority


def _aggregate(node: dict, bb: dict) -> None:
    """Reduce a fanned-out list on the blackboard before the node runs.

    Deliberately a node property rather than a new node kind: it reuses the join
    machinery v1.1 already ships instead of inventing a parallel concept.
    """
    spec = node.get("aggregate")
    if not spec:
        return
    values = bb.get(spec["over"])
    if not isinstance(values, list):
        return
    bb[spec["over"]] = _AGG[spec["op"]](values)


def _fan_out(node: dict, bb: dict, runner, rep: RunReport, visit: int) -> dict:
    """Run a node once per element of `fan_out.over`.

    Each shard produces its own frame, so N shards stay N observations instead of
    collapsing into one blackboard write where the last shard silently wins.
    Declared outputs become *lists* downstream — which is why fan_out is opt-in
    rather than inferred from `parallel_group`.
    """
    spec = node["fan_out"]
    items = bb.get(spec["over"])
    if not isinstance(items, list):
        items = []
    cap = spec.get("max", 40)
    if len(items) > cap:
        # Never silent. A truncated fan-out that reports full coverage is exactly
        # the kind of quiet lie this registry exists to refuse.
        rep.truncations.append(
            f"{node['id']}: fanned out over {cap} of {len(items)} '{spec['over']}' "
            f"items (fan_out.max={cap}); {len(items) - cap} not processed"
        )
    shards, results = items[:cap], []
    for i, item in enumerate(shards):
        out = runner.run(node, {**bb, "shard": item, "shard_index": i, "shard_count": len(shards)})
        rep.frames.append({"node": node["id"], "visit": visit, "shard": i, "out": out})
        results.append(out)
    errs = [r for r in results if r.get("error")]
    on_partial = spec.get("on_partial", "continue")
    keys = set(_shapes.names(node)) | {k for r in results for k in r}
    merged: dict = {k: [r.get(k) for r in results] for k in keys}
    merged["shards_processed"] = len(results)
    merged["shards_failed"] = len(errs)
    if errs and on_partial == "fail":
        merged["error"] = f"{len(errs)} of {len(results)} shards failed"
    return merged


def _search(node: dict, bb: dict, runner, rep: RunReport, visit: int) -> dict:
    """Bounded beam search over candidate outputs.

    This is beam search, not MCTS — no rollout policy and no learned value
    function, because both need a real environment and faking one would produce
    exactly the fixture-deep evidence v1.2 exists to escape. Deterministic,
    inspectable, and bounded by branch x depth.
    """
    spec = node["search"]
    branch, depth = spec.get("branch", 3), spec.get("depth", 2)
    objective = spec.get("objective", "max")
    beam = 1
    if str(spec.get("prune", "")).startswith("beam("):
        beam = int(str(spec["prune"])[5:-1])
    better = (lambda a, b: a < b) if objective == "min" else (lambda a, b: a > b)

    frontier: list[tuple] = [(None, None)]  # (score, candidate)
    log: list[dict] = []
    for d in range(depth):
        scored: list[tuple] = []
        for _, parent in frontier:
            for b in range(branch):
                ctx = {**bb, **(parent or {}), "branch_index": b, "search_depth": d}
                out = runner.run(node, ctx)
                rep.frames.append({"node": node["id"], "visit": visit, "depth": d,
                                   "branch": b, "out": out})
                try:
                    score = safe_eval(spec["score"], {**ctx, **out})
                except UnsafeExpression:
                    raise
                except Exception:  # noqa: S112 — the reason IS the control flow
                    continue  # unscoreable candidate is not a candidate
                # A score that cannot be ordered is no more usable than one that
                # cannot be computed. A real model returned a string here and the
                # sort below took the whole run down with a TypeError instead of
                # dropping one candidate.
                if not isinstance(score, (int, float)) or isinstance(score, bool):
                    continue
                scored.append((score, out))
        if not scored:
            break
        scored.sort(key=lambda sc: sc[0], reverse=(objective == "max"))
        frontier = scored[:beam]
        log.append({"depth": d, "evaluated": len(scored), "best": frontier[0][0]})
    rep.searches.append({"node": node["id"], "rounds": log,
                         "improved": len(log) > 1 and better(log[-1]["best"], log[0]["best"])})
    if not frontier or frontier[0][0] is None:
        return {}
    best_score, best_out = frontier[0]
    return {**best_out, "search_score": best_score, "search_rounds": len(log)}


def _check_state(doc: dict, bb: dict, root, rep: RunReport) -> None:
    """Validate the final blackboard against `state.schema`, if one is declared.

    v1.1 accepted `state.schema` as a string and never read it, deferred to v1.2
    "once it has a consumer". `memory` is that consumer: a graph that persists
    lessons across runs needs its state shape pinned, or the file it accumulates
    becomes untyped sludge. Deferring twice for the same reason is how a spec
    accumulates decoration, so it is enforced here.
    """
    rel = (doc.get("state") or {}).get("schema")
    if not rel or root is None:
        return
    path = Path(root) / rel
    if not path.exists():
        rep.state_violations.append(f"state.schema '{rel}' does not resolve to {path}")
        return
    try:
        import jsonschema

        jsonschema.Draft202012Validator(json.loads(path.read_text())).validate(bb)
    except ImportError:  # pragma: no cover — jsonschema is a hard dependency
        return
    except Exception as ex:
        rep.state_violations.append(f"state does not satisfy {rel}: {ex.args[0] if ex.args else ex}")


def _persist_memory(doc: dict, bb: dict, root, rep: RunReport) -> None:
    """Collect `lessons` and, for `scope: graph`, append them to memory.jsonl.

    A reflexion graph that cannot carry a lesson past the end of one run is a
    retry loop with extra vocabulary. `scope: run` keeps them on the report;
    `scope: graph` persists so the next run reads what the last one learned.
    """
    mem = doc.get("memory")
    if not mem:
        return
    lessons = bb.get("lessons")
    if isinstance(lessons, dict):
        lessons = [lessons]
    if not isinstance(lessons, list):
        return
    rep.lessons = [x for x in lessons if x]
    if mem.get("scope") != "graph" or root is None or not rep.lessons:
        return
    target = Path(root) / "graphs" / doc["category"] / doc["name"] / "memory.jsonl"
    if target.parent.is_dir():
        with target.open("a") as fh:
            for lesson in rep.lessons:
                fh.write(json.dumps({"graph": doc["name"], "lesson": lesson}) + "\n")


def _fire(nid, node, out, doc, out_edges, resolved, taken, forced, pending, bb, rep) -> None:
    """Resolve this node's outgoing edges and enqueue whatever they reach.

    Extracted so a resumed node — whose output is replayed from a journal rather
    than produced by a runner — takes exactly the same routing path as a fresh
    one. Two copies of this logic would let resume diverge from a live run in
    ways the trace-equality test is specifically there to catch.
    """
    errored = bool(out.get("error"))
    blocked = errored or (nid, False) in rep.approvals
    fired: list[int] = []
    for i in out_edges[nid]:
        e = doc["edges"][i]
        kind = e.get("kind", "flow")
        resolved.add(i)
        if kind == "flow" and blocked:
            continue
        if kind == "error" and not errored:
            continue
        if edge_true(e.get("when"), bb):
            fired.append(i)
    if node.get("kind") == "router" and fired:
        fired = fired[:1]
    for i in fired:
        taken.add(i)
        edge = doc["edges"][i]
        tgt = edge["to"]
        if edge.get("kind", "flow") != "flow":
            forced.add(tgt)
        if tgt not in pending:
            pending.append(tgt)


def _bind_evidence(bb: dict, rep: RunReport, since: int) -> None:
    """Put what the tools returned on the blackboard, addressable by ability.

    The gap this closes: `rep.tool_calls` was built for *auditing* — proving a
    command ran. But an assert reads what the model wrote, so a node could make 20
    perfect tool calls and still hand the contract prose, because nothing carried
    the evidence across. `docs-code-sync-audit` failed exactly that way: every
    exit code existed at run time and was summarised into English before it
    reached the blackboard.

    Now an assert can read the fact directly:

        all(c.exit_code == 0 for c in tools.run_command)

    which is checkable without trusting a transcription.
    """
    fresh = [c for c in rep.tool_calls[since:] if c.ok]
    if not fresh:
        return
    tools = dict(bb.get("tools") or {})
    for call in fresh:
        tools.setdefault(call.ability, []).append(call.evidence)
    bb["tools"] = tools


def _reconcile_output(node: dict, out: dict, runner, rep: RunReport) -> dict:
    """Lift declared facts into `output` when the node produced them flat.

    The registry asserts on `output.violations` while a node declares
    `outputs: [violations]`. Those are two conventions for one contract, and a
    model told to return `violations` returns it at top level — correctly. In 10
    of 10 composite failures the required fact was present and only the envelope
    was wrong; every one of them was a real answer scored as a miss.

    This is a harness accommodation, not a model success, so it is recorded on
    `rep.assembled` and reported rather than applied silently. It only ever
    *moves* a value the node already produced — it never invents one, and it never
    overwrites a key the node itself placed inside `output`.
    """
    wanted = runner.contract_for(node)["keys"] if hasattr(runner, "contract_for") else set()
    if not wanted:
        return out
    inner = out.get("output")
    inner = dict(inner) if isinstance(inner, dict) else {}
    lifted = [k for k in wanted if k not in inner and k in out]
    if not lifted:
        return out
    for k in lifted:
        inner[k] = out[k]
    rep.assembled.append(f"{node['id']}: lifted {sorted(lifted)} into output")
    return {**out, "output": inner}


def _run_gate(node: dict, bb: dict, runner, auto_approve: bool, rep: RunReport) -> dict:
    """Execute a `kind: human` approval gate and record its outcome."""
    approve = getattr(runner, "approve", None)
    if approve is not None:
        out = approve(node, bb, auto_approve=auto_approve)
    else:
        out = runner.run(node, bb)
    if auto_approve:
        rep.auto_approved = True
    merged = {**bb, **out}
    contract = node["approval"]["contract"]
    try:
        ok = bool(safe_eval(contract, merged))
    except UnsafeExpression:
        raise  # an approval gate is the last place to fail quietly
    except Exception:
        ok = False
    rep.approvals.append((node["id"], ok))
    return out
