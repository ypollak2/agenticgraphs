"""Every generator must be wired into `make regen`, and every file one writes
must be under `clean-check`.

The 2026-09-12 audit found `docs/live-coverage.md` claiming 38 of 83 graphs
satisfy their contract on every model when a fresh regen said 5 — the project's
headline quality number, wrong by 7.6x, in a file CI never regenerated and never
diffed. `gen_breadth_report.py` and `gen_catalog.py` were the only two `gen_*.py`
scripts in neither the Makefile's `regen` target nor its `clean-check` list.

The repo already had this discipline: the Makefile's own header records that
v1.1 shipped stale CARD.md files because local pytest could not catch them, and
the response was to add the generators to a list. Two were later added and not
put on the list, and nothing noticed for months. So the list is now checked by a
test rather than by memory. A new `scripts/gen_*.py` either joins both lists or
declares itself here with a reason.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
CI = ROOT / ".github" / "workflows" / "ci.yml"

#: Scripts that generate a *scaffold* for a human to edit, not a checked-in
#: artifact that must stay in sync with the tree. Running these in `regen` would
#: rewrite authored content on every CI run. Each needs a reason, so that adding
#: one is a decision and not an omission.
NOT_REGEN = {
    "gen_graphs.py": "scaffolds new graph directories for a human to fill in (one-shot, v1.0)",
    "gen_v2_graphs.py": "one-shot expansion that authored the v2 graphs; rerunning would overwrite them",
    "gen_v3_graphs.py": "one-shot expansion that authored the v3 graphs; rerunning would overwrite them",
}

#: What each wired generator writes, as a path or glob that `clean-check` must
#: cover. Keyed by script name.
WRITES = {
    "gen_cards.py": ["CARDS.md", "graphs/**/CARD.md"],
    "gen_scoreboard.py": ["README.md", "graphs/**/profile.json"],
    "gen_traces.py": ["docs/traces/**"],
    "gen_contract_findings.py": ["docs/contract-findings.md"],
    "gen_clone_report.py": ["reports/*.json"],
    "gen_self_graded.py": ["reports/*.json"],
    "gen_breadth_report.py": ["docs/live-coverage.md"],
    "gen_catalog.py": ["usecases/catalog.yaml"],
    "gen_spec_banners.py": ["docs/agr-v*.md"],
}


def _regen_body() -> str:
    """The lines of the Makefile's `regen` target."""
    body = MAKEFILE.read_text().split("\nregen:\n", 1)[1]
    return body.split("\n\n", 1)[0]


def _clean_check_paths() -> str:
    """The path list `clean-check` hands to `git diff --exit-code`."""
    body = MAKEFILE.read_text().split("\nclean-check:\n", 1)[1]
    return body.split("|| {", 1)[0]


def _generators() -> list[str]:
    return sorted(p.name for p in (ROOT / "scripts").glob("gen_*.py"))


def test_every_generator_is_wired_or_declared():
    regen = _regen_body()
    for name in _generators():
        if name in NOT_REGEN:
            assert NOT_REGEN[name], f"{name} is excluded from regen without a reason"
            assert name not in regen, (
                f"{name} is both declared NOT_REGEN and wired into `regen` — pick one"
            )
            continue
        assert name in regen, (
            f"scripts/{name} is not in the Makefile's `regen` target. Either wire it in "
            f"(and add what it writes to `clean-check` and to WRITES here), or add it to "
            f"NOT_REGEN with the reason it generates a scaffold rather than a tracked artifact."
        )


def test_ci_runs_the_same_generators_as_make_regen():
    """CI is the gate that actually blocks a merge; a Makefile-only wiring is not enough."""
    ci = CI.read_text()
    for name in _generators():
        if name in NOT_REGEN:
            continue
        assert f"scripts/{name}" in ci, f"scripts/{name} runs in `make regen` but not in CI"


def test_clean_check_covers_what_each_generator_writes():
    paths = _clean_check_paths()
    for name, written in WRITES.items():
        if name in NOT_REGEN:
            continue
        for path in written:
            assert path in paths, (
                f"scripts/{name} writes {path}, which `clean-check` does not diff — "
                f"it can drift the way docs/live-coverage.md did (2026-09-12 audit, B4)"
            )


def test_ci_clean_check_matches_the_makefile():
    """The two lists are maintained by hand in two files; they must not diverge."""
    ci = CI.read_text()
    ci_block = ci.split("fail if generated docs are stale", 1)[1].split("|| {", 1)[0]
    for path in re.findall(r"'[^']+'|(?<=\s)[\w./-]+\.(?:md|yaml|json)(?=\s)", _clean_check_paths()):
        assert path in ci_block, f"{path} is diffed by `make clean-check` but not by CI"


@pytest.mark.parametrize("name", sorted(WRITES))
def test_every_wired_generator_declares_what_it_writes(name):
    """WRITES is the map the other tests read; a generator missing from it is invisible to them."""
    assert name in _generators(), f"WRITES names scripts/{name}, which does not exist"
