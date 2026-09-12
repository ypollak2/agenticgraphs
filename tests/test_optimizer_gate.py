"""The optimizer must not accept a mutation it did not measure.

v1.9 found `agr optimize` hill-climbing a constant: it gated every change on
canned fixture replay, which all 83 graphs score 1.0 on, so it could reject a
mutation only for breaking schema. The fix gated on replayed real-model runs.

That fix is sensitive to exactly what the current operators change — edges,
parallel groups, step budgets — and blind to what a node is *told*, because a
replay reuses fixed recorded outputs. A mutation editing a prompt, a description
or a rubric replays byte-identically and passes the quality gate without the gate
having looked at anything. It is the same blind spot as the one v1.9 closed, one
field-type across (2026-09-12 audit, C11).

Every operator that exists today is structural, so these tests guard against a
class of mutation rather than a present bug — which is the cheap moment to do it.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from agenticgraphs.mutate import (
    OPERATORS,
    UNGATEABLE_KEYS,
    optimize,
    touches_ungateable,
)
from agenticgraphs.registry import ROOT, iter_graphs, load


@pytest.fixture
def doc():
    return load(next(p for p in iter_graphs() if p.parent.name == "code-review-pipeline"))


def test_no_change_touches_nothing(doc):
    assert touches_ungateable(doc, copy.deepcopy(doc)) == []


def test_a_structural_change_is_gateable(doc):
    """Edges and budgets decide how a graph runs; replay can judge them."""
    after = copy.deepcopy(doc)
    after["termination"]["max_steps"] = doc["termination"]["max_steps"] + 5
    assert touches_ungateable(doc, after) == []


@pytest.mark.parametrize("field", sorted(UNGATEABLE_KEYS))
def test_editing_what_a_node_is_told_is_detected(doc, field):
    after = copy.deepcopy(doc)
    after["nodes"][0][field] = "something the model is now told"
    found = touches_ungateable(doc, after)
    assert found, f"a change to nodes[0].{field} went undetected"
    assert any(f".{field}" in f for f in found)


def test_removing_a_criteria_is_detected_too(doc):
    """Deletion is a content change; a diff that only looks at present keys misses it."""
    after = copy.deepcopy(doc)
    verifier = next((n for n in after["nodes"] if n.get("criteria")), None)
    if verifier is None:
        pytest.skip("fixture has no node carrying criteria")
    del verifier["criteria"]
    assert touches_ungateable(doc, after)


def test_two_edges_between_the_same_pair_do_not_collide(doc):
    """Edges have no id, so they are keyed by endpoints *and* position."""
    after = copy.deepcopy(doc)
    e = dict(after["edges"][0])
    after["edges"].append(e)
    after["edges"][-1]["guidance"] = "narrate the sequence"
    assert touches_ungateable(doc, after)


def test_every_current_operator_is_structural(doc):
    """If this fails, an operator started editing prompts and needs a live A/B."""
    for op in OPERATORS:
        before = copy.deepcopy(doc)
        candidate = copy.deepcopy(doc)
        ctx = {"profile": None}
        if op(candidate, ctx):
            assert touches_ungateable(before, candidate) == [], (
                f"{op.__name__} edits what a node is told; replay cannot gate it"
            )


def test_optimize_reports_neutral_mutations():
    """A change that replays to the same score moved the registry and not the metric.

    `if score < baseline` accepts it, which is right for cleanup and wrong to do
    silently — 81 optimizations were applied across 71 graphs under that rule.
    """
    res = optimize("code-review-pipeline", apply=False)
    assert "neutral_ops" in res
    assert isinstance(res["neutral_ops"], list)


def test_require_gain_refuses_a_neutral_mutation(monkeypatch):
    """The stricter posture: every accepted change must have earned it."""
    from agenticgraphs import mutate

    name = next(p.parent.name for p in iter_graphs() if p.parent.name == "code-review-pipeline")
    monkeypatch.setattr(mutate, "_live_score", lambda n, d, r=ROOT: (0.5, 4))
    monkeypatch.setattr(mutate, "_cases_still_pass", lambda n, d, r=ROOT: True)
    monkeypatch.setattr(mutate, "OPERATORS", [_op_touch_max_steps])

    lenient = mutate.optimize(name, apply=False)
    strict = mutate.optimize(name, apply=False, require_gain=True)

    assert lenient["notes"], "the lenient default should accept a neutral cleanup"
    assert lenient["neutral_ops"] == ["_op_touch_max_steps"]
    assert not strict["notes"], "require_gain must refuse a mutation with no measured gain"
    assert any("no measured gain" in r["why"] for r in strict["rejected"])


def test_a_content_mutation_is_rejected_not_accepted(monkeypatch):
    """The regression this exists for: an ungateable change must not slip through.

    Both gates would have passed it — fixtures still run, and the replay is
    byte-identical because the recorded outputs never change.
    """
    from agenticgraphs import mutate

    monkeypatch.setattr(mutate, "_live_score", lambda n, d, r=ROOT: (1.0, 4))
    monkeypatch.setattr(mutate, "_cases_still_pass", lambda n, d, r=ROOT: True)
    monkeypatch.setattr(mutate, "OPERATORS", [_op_rewrite_a_prompt])

    res = mutate.optimize("code-review-pipeline", apply=False)
    assert not res["notes"], "a prompt rewrite was accepted without being measured"
    assert res["rejected"], "and it was not even reported"
    assert "replay cannot judge" in res["rejected"][0]["why"]


def _op_touch_max_steps(doc: dict, ctx: dict) -> list[str]:
    doc["termination"]["max_steps"] = doc["termination"]["max_steps"] + 1
    return ["max_steps +1"]


def _op_rewrite_a_prompt(doc: dict, ctx: dict) -> list[str]:
    doc["nodes"][0]["description"] = "a better description, allegedly"
    return ["rewrote nodes[0].description"]


def test_yaml_roundtrip_does_not_itself_look_like_a_content_change(doc):
    """`optimize` compares a yaml round-trip against the live doc; that must be a no-op."""
    assert touches_ungateable(yaml.safe_load(yaml.safe_dump(doc)), doc) == []
