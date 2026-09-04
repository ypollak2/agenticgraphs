"""Stamp every non-current spec doc with a "superseded by" banner.

    uv run python scripts/gen_spec_banners.py

Five spec docs were linked from the README with no in-document signal that later
versions had shipped (2026-09-04 audit, D9-3). The newest version is read from the
`apiVersion` enum in `spec/agr-graph.schema.json`, so the banner can never lag the
schema. Idempotent: an existing banner is replaced, never stacked.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SCHEMA = ROOT / "spec" / "agr-graph.schema.json"

BANNER_RE = re.compile(r"^> \*\*Superseded by \[AGR v[0-9.]+\]\(agr-v[0-9.]+\.md\)\.\*\*.*\n\n", re.M)


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("/v")[1].split("."))


def newest_version() -> str:
    enum = json.loads(SCHEMA.read_text())["properties"]["apiVersion"]["enum"]
    return max(enum, key=_ver).split("/")[1]  # e.g. "v1.8"


def spec_docs() -> list[Path]:
    return sorted(DOCS.glob("agr-v[0-9]*.md"))


def banner(newest: str) -> str:
    return (f"> **Superseded by [AGR {newest}](agr-{newest}.md).** This page describes an earlier "
            f"version and is kept for the record; the current spec is agr-{newest}.md.\n\n")


def stamp(path: Path, newest: str) -> bool:
    """Apply or remove the banner as appropriate. Returns True if the file changed."""
    text = path.read_text()
    stripped = BANNER_RE.sub("", text, count=1)
    current = path.name == f"agr-{newest}.md"
    new = stripped if current else banner(newest) + stripped
    if new != text:
        path.write_text(new)
        return True
    return False


def main() -> int:
    newest = newest_version()
    changed = [p.name for p in spec_docs() if stamp(p, newest)]
    print(f"spec banners: newest {newest}; {len(changed)} file(s) updated" + (f": {changed}" if changed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
