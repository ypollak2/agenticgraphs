"""Locate and load AGR artifacts (graphs, specialities, abilities)."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "spec"


def load_schema(kind: str) -> dict:
    return json.loads((SPEC_DIR / f"agr-{kind}.schema.json").read_text())


def iter_graphs(root: Path = ROOT) -> list[Path]:
    return sorted((root / "graphs").glob("*/*/graph.yaml"))


def iter_yaml(dirname: str, root: Path = ROOT) -> list[Path]:
    return sorted((root / dirname).glob("*.yaml"))


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())
