"""A recording is a measurement, and a measurement is valid only under its conditions.

Every one of the registry's 560 live recordings predates agr/v1.8, which changed
three things that decide what a recording means: the runner stopped passing each
node the asserts it was about to be scored on, sampling was pinned, and 16
self-graded contracts were replaced outright. None of it is comparable to a v1.8
run, so all of it is stamped `superseded_by` and excluded from every reported
number — while the files stay, because a reader deserves to see what was measured
and why it no longer counts.

These tests pin both halves: excluded from the arithmetic, present on disk.
"""
from __future__ import annotations

import json

import pytest

from agenticgraphs.evalcmd import _recordings, eval_graph
from agenticgraphs.registry import ROOT, Registry, live_dir


def test_every_committed_recording_is_stamped():
    """A recording that slipped through unstamped would be silently scored."""
    unstamped = [
        p.relative_to(ROOT) for p in ROOT.glob("graphs/*/*/live/*.json")
        if not json.loads(p.read_text()).get("superseded_by")
    ]
    assert not unstamped, f"pre-v1.8 recordings still counted as evidence: {unstamped[:5]}"


def test_the_files_are_kept_not_deleted():
    """Deleting them would be worse: the numbers they supported are quoted in the
    README and CHANGELOG, and the record of what was measured is the evidence that
    the correction was needed."""
    assert len(list(ROOT.glob("graphs/*/*/live/*.json"))) > 500


def test_no_profile_reports_live_evidence():
    for e in Registry.load():
        assert not e.profile.get("measured_live"), (
            f"{e.name} still publishes a live pass rate from a superseded recording"
        )
        assert e.evidence.tier == "none"


def test_a_superseded_recording_is_not_loaded_for_replay():
    name = "code-review-pipeline"
    case_id = json.loads((ROOT / "graphs" / "software-engineering" / name /
                          "profile.json").read_text())["measured"]["results"][0]["id"]
    assert list(live_dir(name).glob(f"{case_id}*.json")), "fixture precondition: files exist"
    assert _recordings(ROOT, name, case_id) == [], "a superseded recording was replayed"


def test_an_unstamped_recording_is_still_replayed(tmp_path, monkeypatch):
    """The exclusion must be the stamp, not a blanket 'ignore live'. Otherwise
    re-recording would land files that are silently never read."""
    name = "code-review-pipeline"
    src = sorted(live_dir(name).glob("*.json"))[0]
    doc = json.loads(src.read_text())
    doc.pop("superseded_by", None)
    doc.pop("reason", None)

    fresh = live_dir(name) / "zz-v18-probe@test-model.json"
    fresh.write_text(json.dumps(doc, indent=2))
    try:
        found = _recordings(ROOT, name, "zz-v18-probe")
        assert found == [fresh], "an unstamped recording must be replayed"
    finally:
        fresh.unlink()


def test_eval_still_reports_mock_results_with_no_live_evidence():
    """Losing the live tier must not take the mock tier with it — the mechanics
    are still measured, and saying so is the whole point of the two tiers."""
    profile = eval_graph("code-review-pipeline")
    assert profile["measured"]["runner"] == "mock"
    assert profile["measured"]["provisional"] is True
    assert profile["measured"]["pass_rate"] == 1.0
    assert "measured_live" not in profile


@pytest.mark.parametrize("field", ["superseded_by", "reason"])
def test_the_stamp_says_which_version_and_why(field):
    p = sorted(ROOT.glob("graphs/*/*/live/*.json"))[0]
    doc = json.loads(p.read_text())
    assert doc[field], f"a stamp without `{field}` cannot be acted on"
    assert doc["superseded_by"] == "agr/v1.8"


def test_the_live_scoring_path_still_works_when_a_valid_recording_exists(tmp_path):
    """Invalidating the evidence must not quietly break the machinery that reads it.

    Everything `eval_graph` does with live recordings — per-model pass rates,
    disagreement, flakiness, sample widths — is currently unreachable because no
    valid recording exists. That is a state to re-record out of, not a reason for
    the code to rot: this plants two models' worth of unstamped recordings and
    checks the block comes back with the distinctions it is supposed to draw.
    """
    name = "code-review-pipeline"
    case_id = json.loads((ROOT / "graphs" / "software-engineering" / name /
                          "profile.json").read_text())["measured"]["results"][0]["id"]
    template = json.loads(sorted(live_dir(name).glob(f"{case_id}*.json"))[0].read_text())
    template.pop("superseded_by", None)
    template.pop("reason", None)

    cases = {c["id"]: c for c in Registry.load().get(name).cases()}
    good = dict(template, model="model-good", recorded="2026-08-01",
                node_outputs=cases[case_id]["node_outputs"])
    bad = dict(template, model="model-bad", recorded="2026-08-01",
               node_outputs={k: {} for k in cases[case_id]["node_outputs"]})

    planted = []
    try:
        for tag, doc in (("good", good), ("bad", bad)):
            p = live_dir(name) / f"{case_id}@zz-{tag}.json"
            p.write_text(json.dumps(doc, indent=2))
            planted.append(p)
        block = eval_graph(name)["measured_live"]
        assert set(block["models"]) == {"model-good", "model-bad"}
        assert block["per_model_pass_rate"]["model-good"] == 1.0
        assert block["per_model_pass_rate"]["model-bad"] == 0.0
        # One model passing and another failing is the signal that separates a
        # weak model from an unsatisfiable contract, and it must not be averaged.
        assert block["models_disagree"] is True
        assert block["fails_every_model"] is False
        assert block["samples_per_model"] == {"model-good": 1, "model-bad": 1}
    finally:
        for p in planted:
            p.unlink(missing_ok=True)
        eval_graph(name)  # restore the committed profile


def test_a_model_that_both_passes_and_fails_is_reported_as_flaky():
    """`✅` must never quietly mean `passed once`."""
    name = "code-review-pipeline"
    entry = Registry.load().get(name)
    case_id = entry.cases()[0]["id"]
    template = json.loads(sorted(live_dir(name).glob("*.json"))[0].read_text())
    template.pop("superseded_by", None)
    template.pop("reason", None)
    outs = entry.cases()[0]["node_outputs"]

    planted = []
    try:
        for tag, node_outputs in (("s1", outs), ("s2", {k: {} for k in outs})):
            p = live_dir(name) / f"{case_id}@zz-coin#{tag}.json"
            p.write_text(json.dumps(dict(template, model="zz-coin",
                                         recorded="2026-08-01",
                                         node_outputs=node_outputs), indent=2))
            planted.append(p)
        block = eval_graph(name)["measured_live"]
        assert "zz-coin" in block["flaky_models"]
        assert block["samples_per_model"]["zz-coin"] == 2
    finally:
        for p in planted:
            p.unlink(missing_ok=True)
        eval_graph(name)
