"""Executable audit for the use-case catalog. Exits non-zero on violations."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

# v1 motifs (M0) plus the five composite motifs introduced by AGR v1.1.
ALLOWED_PATTERNS = {"pipeline", "parallel-swarm", "router", "debate", "map-reduce",
                    "generator-critic", "planner-executor-verifier", "loop",
                    "lifecycle", "human-gate", "supervisor-hierarchy", "saga",
                    "escalation-ladder"}
REQUIRED = ("id", "name", "domain", "pattern", "summary", "verification")


def audit(path: Path) -> tuple[list[str], dict]:
    doc = yaml.safe_load(path.read_text())
    entries = doc.get("entries", [])
    errors: list[str] = []

    if len(entries) < 100:
        errors.append(f"count: {len(entries)} entries, need >= 100")
    for e in entries:
        for f in REQUIRED:
            if not str(e.get(f, "")).strip():
                errors.append(f"{e.get('id','?')}: missing field '{f}'")
        if e.get("pattern") not in ALLOWED_PATTERNS:
            errors.append(f"{e.get('id','?')}: bad pattern '{e.get('pattern')}'")
    for field in ("id", "name"):
        dupes = [k for k, c in Counter(e.get(field) for e in entries).items() if c > 1]
        if dupes:
            errors.append(f"duplicate {field}s: {dupes}")
    domains = Counter(e.get("domain") for e in entries)
    if len(domains) < 10:
        errors.append(f"domains: {len(domains)}, need >= 10")
    patterns = Counter(e.get("pattern") for e in entries)
    if len(patterns) < 6:
        errors.append(f"patterns used: {len(patterns)}, need >= 6")

    stats = {"entries": len(entries), "domains": dict(sorted(domains.items())),
             "patterns": dict(sorted(patterns.items()))}
    return errors, stats


def main() -> int:
    path = Path(__file__).resolve().parents[1] / "usecases" / "catalog.yaml"
    errors, stats = audit(path)
    print(f"entries: {stats['entries']}")
    print(f"domains ({len(stats['domains'])}): " + ", ".join(f"{k}={v}" for k, v in stats["domains"].items()))
    print(f"patterns ({len(stats['patterns'])}): " + ", ".join(f"{k}={v}" for k, v in stats["patterns"].items()))
    for e in errors:
        print(f"FAIL {e}")
    print("AUDIT " + ("FAILED" if errors else "PASSED"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
