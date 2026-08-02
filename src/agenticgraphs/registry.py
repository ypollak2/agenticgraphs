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


def load_schema(kind: str) -> dict:
    return json.loads((SPEC_DIR / f"agr-{kind}.schema.json").read_text())


def iter_graphs(root: Path = ROOT) -> list[Path]:
    return sorted((root / "graphs").glob("*/*/graph.yaml"))


def iter_yaml(dirname: str, root: Path = ROOT) -> list[Path]:
    return sorted((root / dirname).glob("*.yaml"))


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())
