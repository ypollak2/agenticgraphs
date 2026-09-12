"""Version gates must order `agr/v1.10` above `agr/v1.9`, not below `agr/v1.8`.

Eleven gates in `validate.py` compared `apiVersion` as a raw string until
2026-09-12. `"agr/v1.10" < "agr/v1.8"` is True, so the first two-digit minor
would have classified every new graph as pre-v1.8 and switched a whole
validation tier off — silently, with no error to notice. The limit was written
down in docs/agr-v1.9.md as a known future break; these tests are what stop it
being rediscovered at v1.10.
"""
from __future__ import annotations

import copy

import pytest
import yaml

from agenticgraphs.registry import SPEC_VERSION, iter_graphs, load
from agenticgraphs.validate import _lint_criteria, apiver


def _v(s: str) -> tuple[int, ...]:
    return apiver({"apiVersion": s})


def test_the_break_this_replaces_was_real():
    """The string comparison these gates used to do, preserved as the reason."""
    assert "agr/v1.10" < "agr/v1.8"  # the bug
    assert _v("agr/v1.10") > _v("agr/v1.8")  # the fix


@pytest.mark.parametrize(("lower", "higher"), [
    ("agr/v1", "agr/v1.1"),
    ("agr/v1.1", "agr/v1.2"),
    ("agr/v1.8", "agr/v1.9"),
    ("agr/v1.9", "agr/v1.10"),
    ("agr/v1.10", "agr/v1.11"),
    ("agr/v1.99", "agr/v2.0"),
])
def test_versions_order(lower, higher):
    assert _v(lower) < _v(higher)


def test_bare_major_equals_dot_zero():
    assert _v("agr/v1") == _v("agr/v1.0")


@pytest.mark.parametrize("bad", ["", "agr/v", "agr/vX", "nonsense", "agr/v1.x"])
def test_an_unreadable_version_sorts_below_everything(bad):
    """A graph that does not say what it is must be *checked*, not exempted.

    Sorting an unparseable version low keeps every `< (1, N)` gate on for it.
    """
    assert _v(bad) < _v("agr/v1")
    assert _v(bad) < (1, 8)


@pytest.mark.parametrize("version", ["agr/v1.9", "agr/v1.10", "agr/v2.0"])
def test_a_two_digit_minor_is_still_gated(version):
    """The end-to-end claim: bump a real graph past v1.9 and the v1.8-era lints
    still run against it.

    Under the string compare, `agr/v1.10` sorted below `agr/v1.8` and was skipped
    by nine gates at once. The parametrisation is the point: v1.9 and v1.10 must
    behave identically, and only one of them did.
    """
    doc = load(next(p for p in iter_graphs() if p.parent.name == "code-review-pipeline"))
    assert doc["apiVersion"] == SPEC_VERSION

    broken = copy.deepcopy(doc)
    broken["apiVersion"] = version
    # Strip something only a >= v1.8 gate complains about: a verifier's criteria.
    verifiers = [n for n in broken["nodes"] if n.get("kind") == "verifier"]
    assert verifiers, "this fixture needs a verifier node to strip"
    for node in verifiers:
        node.pop("criteria", None)

    errs = _lint_criteria(broken)
    assert errs, f"a {version} graph was let through a gate a v1.9 graph must pass"


def test_a_genuinely_old_graph_is_still_exempt():
    """The gates must stay off for pre-v1.8 graphs — that is what they are for."""
    doc = load(next(p for p in iter_graphs() if p.parent.name == "code-review-pipeline"))
    old = copy.deepcopy(doc)
    old["apiVersion"] = "agr/v1.7"
    for node in old["nodes"]:
        node.pop("criteria", None)
    assert _lint_criteria(old) == []


def test_every_registry_graph_parses_to_a_version_tuple():
    for path in iter_graphs():
        doc = yaml.safe_load(path.read_text())
        assert apiver(doc) >= (1, 0), f"{path.parent.name} has an unreadable apiVersion"


def test_no_string_version_comparisons_remain():
    """Grep the module, so a reintroduced `< "agr/v1.N"` fails here rather than at v1.10."""
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "agenticgraphs" / "validate.py").read_text()
    offenders = re.findall(r'apiVersion[^\n]*[<>]=?\s*"agr/v', src)
    assert not offenders, f"string-ordered apiVersion comparisons are back: {offenders}"
