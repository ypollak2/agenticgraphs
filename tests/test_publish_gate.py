"""The publish workflow must not hardcode anything that drifts.

`publish.yml` verified the built wheel by asserting `agr list | wc -l` equalled
**52** — the registry's size when the line was written, and 31 graphs stale by
2026-09-12. The job only runs on a tag push, and no tag had been pushed since
`v0.1.1`, so the gate had been failing every release attempt with nobody
watching. The audit recorded "never released" as a finding; it was this line.

A workflow nobody can observe failing needs its invariants checked somewhere
that runs on every commit.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / ".github" / "workflows" / "publish.yml"


def _verify_step() -> str:
    body = PUBLISH.read_text()
    return body.split("Verify the built wheel is self-contained", 1)[1]


def test_the_wheel_check_compares_two_computed_numbers():
    step = _verify_step()
    assert "find graphs -name graph.yaml" in step, (
        "the expected graph count must be derived from the checkout, not typed in"
    )
    assert 'test "$n" -eq "$expected"' in step


def test_no_hardcoded_registry_count_survives():
    """The specific regression: `test "$n" -eq 52`."""
    offenders = re.findall(r'test\s+"\$n"\s+-eq\s+\d+', PUBLISH.read_text())
    assert not offenders, f"publish.yml hardcodes a registry count again: {offenders}"


def test_the_count_the_gate_computes_is_the_one_agr_list_reports():
    """Guard the equivalence the workflow relies on, since CI cannot pip-install here."""
    from agenticgraphs.registry import iter_graphs

    on_disk = len(list(ROOT.glob("graphs/*/*/graph.yaml")))
    assert on_disk == len(iter_graphs()) == 83


def test_publish_still_gates_on_validate_and_tests():
    """Releasing must stay behind the suite, whatever else changes here."""
    body = PUBLISH.read_text()
    assert "agr validate" in body
    assert "pytest -q" in body
