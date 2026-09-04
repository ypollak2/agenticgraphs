"""Refuse a spec bump that leaves the record behind.

    uv run python scripts/check_doc_currency.py

`docs/milestones.md` was one version behind the spec it was introduced as
tracking, 89 minutes after v1.8's own doc landed, and five older spec docs carried
no superseded banner (2026-09-04 audit, D9-4, D9-3, D10-3). Nothing forced the
record to move when the spec did. This does:

1. every `docs/agr-vX.Y.md` has a `docs/milestones.md` entry naming `vX.Y`;
2. every non-current spec doc starts with the generated superseded banner
   (`scripts/gen_spec_banners.py`), and the current one does not;
3. the schema `title` names the newest `apiVersion` in its own enum;
4. every version in the schema enum has a spec doc, and vice versa.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_spec_banners import BANNER_RE, newest_version, spec_docs

ROOT = Path(__file__).resolve().parents[1]
MILESTONES = ROOT / "docs" / "milestones.md"
SCHEMA = ROOT / "spec" / "agr-graph.schema.json"


def main() -> int:
    problems: list[str] = []
    newest = newest_version()
    schema = json.loads(SCHEMA.read_text())
    enum_versions = {v.split("/")[1] for v in schema["properties"]["apiVersion"]["enum"]}
    milestones = MILESTONES.read_text()
    docs = {p.name[len("agr-"):-len(".md")]: p for p in spec_docs()}

    for ver, path in docs.items():
        if not re.search(rf"\bAGR {re.escape(ver)}\b", milestones):
            problems.append(f"{path.name} exists but docs/milestones.md has no entry naming 'AGR {ver}'")
        has_banner = bool(BANNER_RE.match(path.read_text()))
        if ver == newest and has_banner:
            problems.append(f"{path.name} is the current spec but carries a superseded banner")
        if ver != newest and not has_banner:
            problems.append(f"{path.name} is superseded by {newest} but has no banner "
                            "(run scripts/gen_spec_banners.py)")
    if not schema["title"].endswith(newest):
        problems.append(f"schema title {schema['title']!r} does not name the newest enum version {newest}")
    for ver in sorted(enum_versions - docs.keys()):
        # v1 has no dotted doc; every dotted version must.
        if "." in ver:
            problems.append(f"schema enum lists agr/{ver} but docs/agr-{ver}.md does not exist")
    for ver in sorted(docs.keys() - enum_versions):
        problems.append(f"docs/agr-{ver}.md exists but agr/{ver} is not in the schema enum")

    for p in problems:
        print("FAIL " + p)
    if problems:
        return 1
    print(f"OK doc currency: {len(docs)} spec docs, newest {newest}, milestones and banners in step")
    return 0


if __name__ == "__main__":
    sys.exit(main())
