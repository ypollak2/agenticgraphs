"""The registry core: the join every consumer used to re-derive for itself.

These tests pin the two things a refactor must not move — that the join agrees
with the files it joins, and that the evidence tier agrees with what the
scoreboard already publishes — plus the seam (path derivation) the bundle move
depends on.
"""
import json

import pytest

from agenticgraphs.inspect import ability_risks, structural_profile
from agenticgraphs.registry import (
    Evidence,
    Registry,
    iter_graphs,
    load,
    sha,
    shape,
)


@pytest.fixture(scope="module")
def reg():
    return Registry.load()


def test_loads_every_graph(reg):
    assert len(reg) == len(iter_graphs())
    assert all(e.name and e.category and e.doc for e in reg)


def test_get_and_search(reg):
    e = reg.get("code-review-pipeline")
    assert e is not None
    assert e.category == "software-engineering"
    assert reg.get("no-such-graph") is None
    assert e in reg.search("code-review")


def test_search_matches_category_like_the_mcp_tool_always_did(reg):
    """`agr search finance` used to return nothing while MCP returned four."""
    hits = reg.search("finance")
    assert hits, "a domain must be searchable"
    assert all(h.category == "finance" or "finance" in
               (h.name + h.description).lower() for h in hits)


def test_entry_agrees_with_the_files_it_joins(reg):
    for e in reg:
        doc = load(e.path)
        assert e.doc == doc
        assert e.description == doc["description"]
        assert e.contract == doc["termination"].get("contract", "")
        assert e.goal_required == bool((doc.get("goal") or {}).get("required"))
        if e.profile_path.exists():
            assert e.profile == json.loads(e.profile_path.read_text())


def test_structural_matches_the_standalone_profile(reg):
    """The entry must not become a second, drifting definition of the profile."""
    risks = ability_risks()
    for e in reg:
        assert e.structural == structural_profile(e.doc, ability_risk=risks)["structural"]


def test_evidence_tier_matches_the_published_profile(reg):
    """Tier is lifted from gen_scoreboard's markers -- it must not reclassify."""
    for e in reg:
        block = e.profile.get("measured_live") or {}
        if not block:
            assert e.evidence.tier == "none"
            continue
        if block.get("fails_every_model"):
            assert e.evidence.tier == "unsatisfiable"
        elif block.get("flaky_models"):
            assert e.evidence.tier == "flaky"
        elif block.get("models_disagree"):
            assert e.evidence.tier == "models-disagree"
        elif block.get("pass_rate") == 1.0:
            assert e.evidence.tier == "satisfied-all"
        assert e.evidence.models == tuple(block.get("models", ()))
        assert e.evidence.samples_per_model == block.get("samples_per_model", {})


def test_min_samples_exposes_the_n_equals_1_cells(reg):
    """A2 grades these `unproven`; A1 only has to make them countable.

    The registry currently holds no VALID recordings — every one predates agr/v1.8
    and is stamped `superseded_by` (see scripts/invalidate_recordings.py), so there
    are no cells of any width to count. The property being pinned is the one that
    outlives that: any cell the registry does report must report its own width, so
    a single sample can never pass for a measurement.
    """
    thin = [e for e in reg if 0 < e.evidence.min_samples < 2]
    for e in thin:
        assert min(e.evidence.samples_per_model.values()) == 1
    if not any(e.evidence.min_samples for e in reg):
        pytest.skip("no valid recordings: the v1.8 evidence base is pending re-recording")


def test_evidence_absent_is_not_evidence_of_absence():
    ev = Evidence.from_profile({})
    assert ev.tier == "none"
    assert ev.models == ()
    assert ev.min_samples == 0


def test_paths_resolve_to_real_files(reg):
    """The seam the bundle move edits. If these drift, A0 breaks silently."""
    for e in reg:
        assert e.path.exists()
        assert e.has_cases, f"{e.name} has no cases.yaml"
        assert e.cases(), f"{e.name} has empty cases"
        assert e.recordings(), f"{e.name} has no recordings"
        assert e.profile_path.exists() and e.card_path.exists()


def test_recordings_filter_by_case(reg):
    e = reg.get("code-review-pipeline")
    ids = {c["id"] for c in e.cases()}
    assert sum(len(e.recordings(i)) for i in ids) == len(e.recordings())


def test_shape_hash_ignores_prose_but_not_structure(reg):
    e = reg.get("code-review-pipeline")
    reworded = dict(e.doc, description="something else entirely")
    assert sha(shape(reworded)) == e.shape_sha
    assert sha(reworded) != e.sha, "the full hash must still notice"

    restructured = dict(e.doc, nodes=e.doc["nodes"][:-1])
    assert sha(shape(restructured)) != e.shape_sha


def test_uncovered_is_the_expansion_backlog(reg):
    uncovered = reg.uncovered()
    names = {e.name for e in reg}
    assert all(row["name"] not in names for row in uncovered)
    assert len(uncovered) + len(reg) == len(
        load(reg.root / "usecases" / "catalog.yaml")["entries"]
    )


def test_use_case_comes_from_the_bundle_not_the_catalog(reg):
    """The entry lives with the graph; catalog.yaml is a projection of it."""
    for e in reg:
        uc = e.path.parent / "usecase.yaml"
        assert uc.exists(), f"{e.name} has no usecase.yaml"
        raw = load(uc)
        assert raw["id"].startswith("uc-")
        # name/domain are derived, never stored twice, so they cannot disagree
        assert "name" not in raw and "domain" not in raw
        assert e.entry["name"] == e.name and e.entry["domain"] == e.category
        assert e.motif == raw["pattern"]


def test_catalog_is_a_faithful_projection(reg):
    """Regenerating from the bundles must reproduce every committed row."""
    committed = {r["name"]: r for r in
                 load(reg.root / "usecases" / "catalog.yaml")["entries"]}
    for e in reg:
        assert committed[e.name] == e.entry
    for row in reg.uncovered():
        assert committed[row["name"]] == row
    assert len(committed) == len(reg) + len(reg.uncovered())


def test_backlog_ids_do_not_collide_with_shipped_ones(reg):
    ids = [e.entry["id"] for e in reg] + [r["id"] for r in reg.uncovered()]
    assert len(ids) == len(set(ids)), "use-case ids must be unique across both sources"
