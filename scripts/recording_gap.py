"""Which graphs still need recording, and how deep.

Recording the registry against a local model takes hours, and the sweep has been
SIGKILLed four times by memory pressure — an 18.6GB model alongside the harness is
more than this machine holds. Resumability is therefore not a convenience: without
it every kill discards everything and the sweep can never finish.

`AGR_TARGET_SAMPLES` also lets breadth come before depth. A complete one-sample
baseline says something about all 83 graphs; a three-sample baseline over the first
31 says something about a slice, and reading a pass rate off a slice is the failure
`docs/live-coverage.md` exists to prevent. So: n=1 everywhere, then go back for
n=2 and n=3.

    AGR_TARGET_SAMPLES=1 uv run python scripts/recording_gap.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import (
    SPEC_VERSION,
    cases_path,
    iter_graphs,
    live_dir,
    load,
)


def missing(target: int) -> list[str]:
    """Graphs with any case short of `target` recordings at the current spec.

    Per CASE, not per graph. `record_live.py` recorded `cases[0]` only for the
    whole life of the project, so a graph with one deep case and one unrecorded
    case reads as covered unless the count is taken case by case.
    """
    todo: list[str] = []
    for gpath in iter_graphs():
        name = load(gpath)["name"]
        cases = [c["id"] for c in yaml.safe_load(cases_path(name).read_text())["cases"]]
        per = dict.fromkeys(cases, 0)
        for p in live_dir(name).glob("*.json"):
            doc = json.loads(p.read_text())
            if doc.get("superseded_by") or doc.get("spec") != SPEC_VERSION:
                continue
            for case_id in cases:
                if p.name.startswith(case_id + "@"):
                    per[case_id] += 1
                    break
        if any(v < target for v in per.values()):
            todo.append(name)
    return todo


def main() -> int:
    """Print one graph name per line, and NOTHING when there is nothing to do.

    `print("\n".join([]))` emits a blank line, so `wc -l` reported 1 for an empty
    list — every "1 remaining" was really 0, and the waiters watching for `-eq 0`
    never fired. A tool that reports progress must be able to report completion.
    """
    todo = missing(int(os.environ.get("AGR_TARGET_SAMPLES", "1")))
    if todo:
        print("\n".join(todo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
