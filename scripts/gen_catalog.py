"""Project `usecases/catalog.yaml` from the per-artifact sources.

The catalog used to BE this file: 131 use cases in a Python list, edited by every
contributor, regenerating a YAML nobody could edit directly. That made adding one
graph a write to a file every other graph shares, which is what turned parallel
authoring into a rebase queue.

The entry now lives with the thing it describes:

  * a use case that HAS a graph  -> `graphs/<domain>/<name>/usecase.yaml`,
    carrying only what the graph does not already say. `name` and `domain` are
    read off the graph, so they cannot drift from it.
  * a use case with NO graph yet -> `usecases/backlog/<name>.yaml`, carrying all
    six fields because there is no graph to derive them from.

Writing a graph for a backlog entry is therefore a `git mv` plus dropping the two
derived fields — and it touches no file any other author is touching.

`id` is preserved verbatim and the catalog is emitted in id order, because ids are
public: `gen_cards.py` renders them as the `AGR-NNN` card identifier.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agenticgraphs.registry import Registry, load  # noqa: E402

FIELDS = ("id", "name", "domain", "pattern", "summary", "verification")


def entries() -> list[dict]:
    """Every use case, from both sources, in id order."""
    out = []
    for e in Registry.load(ROOT):
        p = e.path.parent / "usecase.yaml"
        if not p.exists():
            continue
        uc = load(p)
        out.append({"id": uc["id"], "name": e.name, "domain": e.category,
                    "pattern": uc["pattern"], "summary": uc["summary"],
                    "verification": uc["verification"]})
    for p in sorted((ROOT / "usecases" / "backlog").glob("*.yaml")):
        uc = load(p)
        out.append({k: uc[k] for k in FIELDS})
    return sorted(out, key=lambda e: e["id"])


def main() -> int:
    rows = entries()
    dupes = {e["id"] for e in rows if sum(1 for x in rows if x["id"] == e["id"]) > 1}
    if dupes:
        print(f"FAIL duplicate ids: {sorted(dupes)}", file=sys.stderr)
        return 1
    out = ROOT / "usecases" / "catalog.yaml"
    out.write_text(yaml.safe_dump(
        {"apiVersion": "agr/v1", "kind": "UseCaseCatalog", "entries": rows},
        sort_keys=False, width=120, allow_unicode=True))
    print(f"wrote {out.relative_to(ROOT)} with {len(rows)} entries "
          f"({sum(1 for e in rows if (ROOT / 'usecases' / 'backlog' / (e['name'] + '.yaml')).exists())} "
          f"still without a graph)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
