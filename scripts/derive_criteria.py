"""Give every verifier node the rubric it needs to be a verifier.

Until v1.8 a node carried its position in a topology — `speciality`, `abilities`,
`outputs` — and nothing else. That is why `clinical-literature-triage` and
`incident-triage-router` were the same four nodes differing in name, description
and category: a healthcare graph containing no healthcare, and a registry where
36 of 83 graphs were byte-identical to another once those strings were stripped.

The rubric is the domain knowledge, and there was no field to hold it. `criteria`
is that field. It is also what the runner gives a node in place of the assert
text it used to leak (see `LLMRunner.run`): an assert is the marking scheme and
telling a node its marking scheme measures echo, while criteria are what the
claim MEANS in this domain, which is the thing a verifier has to reason about.

Each entry below was written against the graph's own description, termination
contract and asserts, then reviewed against one rule: criteria say what to judge,
never which flag to set. "output.matches_ownership_map is true" restates the
assert; "the team owns the affected service in the current on-call map" is the
judgement the assert is trying to stand for.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.registry import iter_graphs, load

CRITERIA: dict[str, str] = json.loads((Path(__file__).parent / "criteria.json").read_text())

TARGET = "agr/v1.8"


def main() -> int:
    written = bumped = 0
    missing: list[str] = []
    for gpath in iter_graphs():
        doc = load(gpath)
        changed = False
        verifiers = [n for n in doc["nodes"] if n.get("kind") == "verifier"]
        text = CRITERIA.get(doc["name"])
        if verifiers and not text:
            missing.append(doc["name"])
        for n in verifiers:
            if text and n.get("criteria") != text:
                n["criteria"] = text
                changed = True
                written += 1
        if doc.get("apiVersion") != TARGET:
            doc["apiVersion"] = TARGET
            bumped += 1
            changed = True
        if changed:
            gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    print(f"criteria written on {written} verifier nodes; {bumped} graphs bumped to {TARGET}")
    if missing:
        print(f"MISSING criteria for verifier nodes in: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
