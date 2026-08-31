"""Self-graded contracts hide inside `and` / `or` too.

`_lint_self_graded` matches a bare truthy read of one key. Ten contracts wrap the
same thing in a boolean combination and slipped through:

    output.verified == true or output.escalated == true
    output.lint_passed and output.plagiarism_clean

Every term is a verdict the graph's own model wrote. Combining two unfalsifiable
claims with `and` does not make either falsifiable, and the first v1.8 recording
sweep found `verifier-swarm` failing this 9 times out of 9 — a contract that could
only ever be satisfied by the model asserting it, failing because the model did
not bother to assert it.

Seven of the ten already carry a `verification[].command` that settles the same
question by exit code. There the flag is not merely weak, it is *redundant*: a
second, worse claim about a fact already established. Those lose the flag and keep
the command.

The rest are replaced by counts and comparisons — `len(output.bias_terms) == 0`
rather than `output.bias_lint_clean` — because a count is a thing the output either
contains or does not, and a verdict is a thing a model can simply say.

**Not every truthy term is a verdict.** `output.advisory_url and output.cve_id`
reads two *values*; their truthiness is a presence check on named artefacts, which
is the weakest legitimate form rather than a self-grade. The widened lint tells
them apart by declared shape: a term declared `bool` is a verdict, anything else
is a value. That is what the shape declarations are for.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.inspect import find_graph  # noqa: E402
from agenticgraphs.registry import cases_path, load  # noqa: E402

# graph -> (new verification list, {node: outputs}, {node: case outputs})
FIXES: dict[str, tuple] = {
    # --- redundant beside an executable command -------------------------------
    "verifier-swarm": (
        [{"describe": "the caller's own verification command exits 0 — the exit code is "
                      "the fact, and nothing merges before it",
          "command": "{verify_command}"},
         {"describe": "the retry loop is bounded: three failures escalate rather than "
                      "becoming a fourth attempt",
          "assert": "output.attempts <= 3"}],
        {"verifier": [{"attempts": "int"}, "escalated", "output"]},
        {"verifier": {"attempts": 1, "escalated": False,
                      "output": {"attempts": 1, "escalated": False}}},
    ),
    "self-healing-ci": (
        [{"describe": "the pipeline is re-run to prove it is green, not reported green",
          "command": "pytest -q"},
         {"describe": "every attempt is recorded as a lesson, so the next run does not "
                      "retry what already did not work",
          "assert": "len(output.lessons) >= 1 and output.attempts <= 3"}],
        {"confirm": [{"attempts": "int"}, "escalated", {"lessons": "list"}, "output"]},
        {"confirm": {"attempts": 1, "escalated": False, "lessons": ["cache was stale"],
                     "output": {"attempts": 1, "lessons": ["cache was stale"]}}},
    ),
    "bug-triage-and-fix": (
        [{"describe": "the regression test is run before and after the patch; the exit "
                      "codes are the fact, not a verdict about them",
          "assert": "output.exit_before != 0 and output.exit_after == 0"},
         {"describe": "the suite is run", "command": "pytest -q {test_path}"}],
        {"verify": [{"exit_after": "int"}, {"exit_before": "int"}, "output"]},
        {"verify": {"exit_before": 1, "exit_after": 0,
                    "output": {"exit_before": 1, "exit_after": 0}}},
    ),
    "dependency-upgrade": (
        [{"describe": "the lockfile actually changed — a digest before and after, not a "
                      "claim that it was updated",
          "assert": "output.lockfile_sha_before != output.lockfile_sha_after"},
         {"describe": "no new deprecation was introduced; a green suite that emits them "
                      "has deferred the breakage, not avoided it",
          "assert": "len(output.new_deprecations) == 0"},
         {"describe": "the suite passes against the upgraded lockfile", "command": "pytest -q"}],
        {"produce": ["lockfile_sha_after", "lockfile_sha_before", {"new_deprecations": "list"}],
         "review": ["lockfile_sha_after", "lockfile_sha_before", {"new_deprecations": "list"},
                    "output"]},
        {"produce": {"lockfile_sha_before": "aaa", "lockfile_sha_after": "bbb",
                     "new_deprecations": []},
         "review": {"lockfile_sha_before": "aaa", "lockfile_sha_after": "bbb",
                    "new_deprecations": [],
                    "output": {"lockfile_sha_before": "aaa", "lockfile_sha_after": "bbb",
                               "new_deprecations": []}}},
    ),
    "sql-generation-verified": (
        [{"describe": "the query ran, read off the exit code the `execute` node recorded",
          "assert": "output.exit_code == 0"},
         {"describe": "the result is not vacuous — a query returning nothing from a "
                      "populated table is wrong even though it ran",
          "assert": "output.row_count > 0"},
         {"describe": "the query is executed against the real schema",
          "command": "psql -v ON_ERROR_STOP=1 -f {query_path}"}],
        {"critique": [{"exit_code": "int"}, "output", {"row_count": "int"}]},
        {"critique": {"exit_code": 0, "row_count": 12,
                      "output": {"exit_code": 0, "row_count": 12}}},
    ),
    "schema-migration-saga": (
        [{"describe": "either the migration reached parity — two row counts agreeing, not "
                      "a model reporting that they do — or every executed step was "
                      "compensated back",
          "assert": "output.source_rows == output.target_rows or "
                    "output.compensated_steps == output.executed_steps"},
         {"describe": "the migration and its compensator both run, so reversibility is "
                      "demonstrated rather than asserted",
          "command": "alembic upgrade head"}],
        {"verify": [{"source_rows": "int"}, {"target_rows": "int"}],
         "undo-shadow": [{"compensated_steps": "int"}, {"executed_steps": "int"}, "output",
                         {"source_rows": "int"}, {"target_rows": "int"}]},
        {"verify": {"source_rows": 1000, "target_rows": 1000},
         "undo-shadow": {"source_rows": 1000, "target_rows": 1000,
                         "compensated_steps": 0, "executed_steps": 3,
                         "output": {"source_rows": 1000, "target_rows": 1000,
                                    "compensated_steps": 0, "executed_steps": 3}}},
    ),
    "vuln-remediation-lifecycle": None,  # values, not verdicts — see the module docstring
    # --- no command available: counts instead of verdicts ----------------------
    "blog-production-pipeline": (
        [{"describe": "the style guide reports zero violations — a count the reader can "
                      "check against the draft, not a lint verdict",
          "assert": "len(output.style_violations) == 0"},
         {"describe": "no passage matches published text beyond an incidental phrase",
          "assert": "output.max_match_ratio < 0.15"}],
        {"produce": [{"max_match_ratio": "float"}, {"style_violations": "list"}],
         "review": [{"max_match_ratio": "float"}, "output", {"style_violations": "list"}]},
        {"produce": {"style_violations": [], "max_match_ratio": 0.02},
         "review": {"style_violations": [], "max_match_ratio": 0.02,
                    "output": {"style_violations": [], "max_match_ratio": 0.02}}},
    ),
    "kb-article-generator": (
        [{"describe": "every step names the action and the result to expect, so someone "
                      "who never saw the ticket can follow it",
          "assert": "all(s.action and s.expected for s in output.steps)"},
         {"describe": "nothing in the existing base covers the same symptom",
          "assert": "len(output.near_duplicates) == 0"}],
        {"produce": [{"near_duplicates": "list"},
                     {"steps": "list[{action:any, expected:any}]"}],
         "review": [{"near_duplicates": "list"}, "output",
                    {"steps": "list[{action:any, expected:any}]"}]},
        {"produce": {"steps": [{"action": "clear cache", "expected": "login succeeds"}],
                     "near_duplicates": []},
         "review": {"steps": [{"action": "clear cache", "expected": "login succeeds"}],
                    "near_duplicates": [],
                    "output": {"steps": [{"action": "clear cache",
                                          "expected": "login succeeds"}],
                               "near_duplicates": []}}},
    ),
    "jd-drafting-critic": (
        [{"describe": "no gendered or coded term survives — the terms found, not a verdict "
                      "that none were",
          "assert": "len(output.bias_terms) == 0"},
         {"describe": "requirements are deduplicated, checked by counting rather than "
                      "claiming",
          "assert": "len(output.requirements) == len(output.unique_requirements)"}],
        {"critique": [{"bias_terms": "list"}, "output", {"requirements": "list"},
                      {"unique_requirements": "list"}]},
        {"critique": {"bias_terms": [], "requirements": ["python"],
                      "unique_requirements": ["python"],
                      "output": {"bias_terms": [], "requirements": ["python"],
                                 "unique_requirements": ["python"]}}},
    ),
}


def main() -> int:
    changed = []
    for name, spec in FIXES.items():
        if spec is None:
            continue
        verification, node_outputs, case_outputs = spec
        gpath = find_graph(name)
        doc = load(gpath)
        doc["verification"] = verification
        for nid, outs in node_outputs.items():
            node = next(n for n in doc["nodes"] if n["id"] == nid)
            node["outputs"] = outs
        gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))

        cpath = cases_path(name)
        data = yaml.safe_load(cpath.read_text())
        for case in data["cases"]:
            for nid, outs in case_outputs.items():
                existing = case["node_outputs"].get(nid) or {}
                merged = {**existing, **outs}
                merged["output"] = {**(existing.get("output") or {}),
                                    **(outs.get("output") or {})}
                case["node_outputs"][nid] = merged
        cpath.write_text(yaml.safe_dump(data, sort_keys=False, width=100))
        changed.append(name)
    print(f"replaced {len(changed)} compound self-graded contracts: {changed}")
    print("re-record these — their prior recordings measured the contract they replace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
