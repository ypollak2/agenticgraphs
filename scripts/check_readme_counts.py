"""Every number the README states about the registry, checked against the registry.

    uv run python scripts/check_readme_counts.py          # exit 1 on any drift
    uv run python scripts/check_readme_counts.py --fix    # rewrite the badges

Two generated blocks in the README were CI-checked; every other number was
hand-typed and drifted (52/74 graphs, 112/123 use cases, 19 motifs, 204 tests —
2026-09-04 audit, D9-6). This script owns the badges and refuses any count
sentence outside the generated blocks that disagrees with the source of truth:

- graphs, domains, tiers  -> the registry (`iter_graphs`)
- use cases               -> `usecases/catalog.yaml`
- motifs                  -> the distinct `pattern` of every shipped graph, and the
                             README motif tables must name exactly that set
- tests                   -> `pytest --collect-only -q`
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import ROOT, iter_graphs, load

README = ROOT / "README.md"
CATALOG = ROOT / "usecases" / "catalog.yaml"

_BADGE = re.compile(r"^\[(?P<key>[a-z-]+)-shield\]: https://img\.shields\.io/badge/(?P<label>[^-]+(?:--[^-]+)*)-(?P<value>[^-]+)-(?P<rest>.+)$", re.M)
_GENERATED = re.compile(r"<!-- [a-z-]+:begin -->.*?<!-- [a-z-]+:end -->", re.S)
_MOTIF_ROW = re.compile(r"^\| `([a-z0-9-]+)` \| .+ \| `[a-z0-9-]+` \|$", re.M)


def truth() -> dict[str, int | set[str]]:
    docs = [load(g) for g in iter_graphs()]
    catalog = yaml.safe_load(CATALOG.read_text())["entries"]
    by_name = {e["name"]: e for e in catalog}
    shipped_patterns = {by_name[d["name"]]["pattern"] for d in docs if d["name"] in by_name}
    tiers = Counter("composite" if any(n.get("kind") == "subgraph" for n in d["nodes"])
                    else "primitive" for d in docs)
    return {
        "graphs": len(docs),
        "domains": len({d["category"] for d in docs}),
        "usecases": len(catalog),
        "motifs": len(shipped_patterns),
        "motif_set": shipped_patterns,
        "primitives": tiers["primitive"],
        "composites": tiers["composite"],
        "tests": collected_tests(),
    }


def collected_tests() -> int:
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                          "--no-cov"], cwd=ROOT, capture_output=True, text=True).stdout
    m = re.search(r"(\d+) tests? collected", out)
    if not m:
        raise SystemExit("could not count tests: " + out[-400:])
    return int(m.group(1))


#: badge key -> (truth key, badge label as it appears in the URL)
BADGES = {
    "graphs": ("graphs", "graphs"),
    "usecases": ("usecases", "use--case_catalog"),
    "domains": ("domains", "domains"),
    "patterns": ("motifs", "motifs"),
    "tests": ("tests", "tests"),
}

#: count sentences outside the generated blocks: regex -> truth key
SENTENCES = {
    re.compile(r"\b(\d+) (?:shipped |registry )?graphs\b"): "graphs",
    re.compile(r"\b(\d+)[- ]entry use-case catalog\b"): "usecases",
    re.compile(r"\b(\d+) use cases\b"): "usecases",
    re.compile(r"\b(\d+) (?:verified )?motifs\b"): "motifs",
    re.compile(r"\b(\d+) domains\b"): "domains",
    re.compile(r"\b(\d+) primitives\b"): "primitives",
    re.compile(r"\b(\d+) composites\b"): "composites",
}


def check(text: str, t: dict, fix: bool) -> tuple[str, list[str]]:
    problems: list[str] = []

    def badge(m: re.Match) -> str:
        key = m.group("key")
        if key not in BADGES:
            return m.group(0)
        tkey, label = BADGES[key]
        want = str(t[tkey])
        if m.group("label") != label:
            return m.group(0)
        if m.group("value") != want:
            if fix:
                return f"[{key}-shield]: https://img.shields.io/badge/{label}-{want}-{m.group('rest')}"
            problems.append(f"badge {key}: README says {m.group('value')}, registry says {want}")
        return m.group(0)

    text = _BADGE.sub(badge, text)

    # Blank the generated blocks but keep their newlines so line numbers hold.
    prose = _GENERATED.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    for rx, tkey in SENTENCES.items():
        for m in rx.finditer(prose):
            if prose[max(0, m.start() - 2):m.start()].strip() in ("≥", ">=", "<", "<=", ">"):
                continue  # a threshold ("≥10 domains"), not a count
            if int(m.group(1)) != t[tkey]:
                line = prose.count("\n", 0, m.start()) + 1
                problems.append(f"prose (README.md:{line}): '{m.group(0)}' but the registry says {t[tkey]}")

    tables = set(_MOTIF_ROW.findall(prose))
    missing = t["motif_set"] - tables
    extra = tables - t["motif_set"]
    if missing:
        problems.append(f"motif tables omit shipped motifs: {sorted(missing)}")
    if extra:
        problems.append(f"motif tables name motifs no shipped graph implements: {sorted(extra)}")
    return text, problems


def main(argv: list[str] | None = None) -> int:
    fix = "--fix" in (argv if argv is not None else sys.argv[1:])
    t = truth()
    text = README.read_text()
    new, problems = check(text, t, fix)
    if fix and new != text:
        README.write_text(new)
        print("rewrote README badges")
    for p in problems:
        print("FAIL " + p)
    if problems:
        return 1
    print(f"OK README counts: {t['graphs']} graphs, {t['domains']} domains, {t['usecases']} use cases, "
          f"{t['motifs']} motifs, {t['primitives']}+{t['composites']} tiers, {t['tests']} tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
