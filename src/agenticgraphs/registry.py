"""Locate and load AGR artifacts (graphs, specialities, abilities)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

def _resolve_root() -> Path:
    """Locate the registry payload.

    An installed wheel carries the registry under ``agenticgraphs/data/`` (see the
    force-include block in pyproject.toml); a git checkout keeps it at the repo root
    so the graphs stay browsable on GitHub and the CARD.md relative links resolve.
    Prefer the packaged copy, fall back to the checkout layout.
    """
    packaged = Path(__file__).resolve().parent / "data"
    if (packaged / "graphs").is_dir():
        return packaged
    return Path(__file__).resolve().parents[2]


ROOT = _resolve_root()
SPEC_DIR = ROOT / "spec"

#: The spec revision every registry graph is written against. One source of truth,
#: so a migration cannot leave stragglers and a test cannot freeze the number.
#:
#: NOTE `agr/v1.6` is deliberately skipped by the registry. It is not a dead number:
#: `_lint_provenance` arms a hard provenance error for graphs declaring exactly
#: v1.6, as a staged opt-in that authors take one graph at a time. Migrating the
#: registry onto v1.6 wholesale would arm that escalation for 83 graphs that were
#: never reviewed for it — `clinical-protocol-lifecycle` asserts `registry_id`, a
#: ground-truth field no binding here can obtain, so it would fail on a rule about
#: provenance while the actual change was about goals.
SPEC_VERSION = "agr/v1.7"


def load_schema(kind: str) -> dict:
    return json.loads((SPEC_DIR / f"agr-{kind}.schema.json").read_text())


def iter_graphs(root: Path = ROOT) -> list[Path]:
    return sorted((root / "graphs").glob("*/*/graph.yaml"))


def iter_yaml(dirname: str, root: Path = ROOT) -> list[Path]:
    return sorted((root / dirname).glob("*.yaml"))


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())
