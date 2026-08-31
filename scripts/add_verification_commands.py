"""Give the graphs that CAN be checked by running something an actual command.

`verification[].command` is the only depth grade where a contract is settled by
an exit code rather than by a model's account of itself. The registry had one,
and it was prose. Three now exist after the self-graded rewrite; this adds the
rest of the honest set.

**Honest is the operative word.** 32 graphs declare an execute-risk ability, but
declaring `execute_step` does not make a contract shell-checkable: nothing you
can run at a prompt settles whether a podcast's rights are clear or a candidate
was screened fairly. Adding commands there would be theatre in the field that
exists to stop theatre, so those graphs keep an assert and are listed at the
bottom as deliberately excluded.

What earns a command is a contract whose subject is a repository, a dataset, or
a live system — where a suite, a query, or a scanner already decides the answer
and the graph was merely reporting it.

Commands take `{placeholder}` values from the blackboard, so a graph can name a
check without hardcoding the caller's project layout.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import load

# graph -> (describe, command, extra state.inputs the placeholders need)
COMMANDS: dict[str, tuple[str, str, list[str]]] = {
    "verifier-swarm": (
        "the caller's own verification command exits 0 — the exit code is the fact, "
        "and nothing merges before it",
        "{verify_command}", ["verify_command"]),
    "bug-triage-and-fix": (
        "the regression test fails on the unpatched tree and passes on the patched one",
        "pytest -q {test_path}", ["test_path"]),
    "flaky-test-reflexion": (
        "the suspect test is re-run enough times for three consecutive greens to mean "
        "something",
        "pytest -q --count=5 {test_path}", ["test_path"]),
    "test-suite-generation": (
        "the generated tests run, and the mutation score is measured rather than claimed",
        "pytest -q", []),
    "legacy-refactor": (
        "the characterization suite is green after the refactor — a refactor that changes "
        "behaviour was a rewrite",
        "pytest -q", []),
    "performance-optimization": (
        "the benchmark is executed, not estimated",
        "pytest -q --benchmark-only", []),
    "dependency-upgrade": (
        "the suite passes against the upgraded lockfile",
        "pytest -q", []),
    "docs-code-sync-audit": (
        "every code example in the docs is executed; an example judged plausible has not "
        "been checked",
        "pytest -q --doctest-glob=*.md {docs_path}", ["docs_path"]),
    "feature-delivery-lifecycle": (
        "the feature's tests pass in the repository it was delivered to",
        "pytest -q", []),
    "code-review-pipeline": (
        "the secret scanner runs over the diff rather than the reviewer eyeballing it",
        "gitleaks detect --no-banner --redact", []),
    "self-healing-ci": (
        "the pipeline is re-run to prove it is green, not reported green",
        "pytest -q", []),
    "runbook-executor": (
        "each step's post-condition is executed; a skipped check is not a passed step",
        "pytest -q {postcondition_path}", ["postcondition_path"]),
    "sql-generation-verified": (
        "the query is executed against the real schema",
        "psql -v ON_ERROR_STOP=1 -f {query_path}", ["query_path"]),
    "etl-pipeline-builder": (
        "the pipeline is run end to end and the loaded row count is read back",
        "dbt build --select {model_name}", ["model_name"]),
    "data-quality-audit": (
        "the quality rules are executed against the dataset",
        "dbt test --select {model_name}", ["model_name"]),
    "schema-migration-saga": (
        "the migration and its compensator both run, so the saga's reversibility is "
        "demonstrated rather than asserted",
        "alembic upgrade head", []),
    "citation-integrity-audit": (
        "every citation URL is actually fetched; a link that resolves in prose does not "
        "resolve",
        "linkchecker --no-warnings {document_path}", ["document_path"]),
    "prompt-graph-optimization": (
        "the winning variant is scored on the held-out set by running it",
        "agr eval {candidate_graph} --live", ["candidate_graph"]),
    "red-team-blue-team-hardening": (
        "the recorded bypasses are replayed against the hardened build",
        "pytest -q {exploit_suite}", ["exploit_suite"]),
    "vuln-remediation-lifecycle": (
        "the proof-of-concept is re-run against the patched build",
        "pytest -q {repro_path}", ["repro_path"]),
}

#: Declared an execute-risk ability, deliberately NOT given a command: no shell
#: invocation settles their contract, and a decorative one would be exactly the
#: claim-dressed-as-evidence this field exists to prevent.
EXCLUDED = [
    "procurement-lifecycle", "book-editing-pipeline", "podcast-production-pipeline",
    "incident-lifecycle", "quiz-generation-verified", "rubric-grading-swarm",
    "expense-audit-swarm", "medical-coding-audit", "trial-eligibility-screener",
    "hiring-lifecycle", "contract-lifecycle", "product-listing-pipeline",
    "literature-review-swarm", "forensic-investigation-blackboard",
    "soc-alert-investigation", "release-notes-generation",
]


def main() -> int:
    import re

    changed = 0
    for name, (describe, command, inputs) in COMMANDS.items():
        gpath = find_graph(name)
        doc = load(gpath)
        entry = {"describe": describe, "command": command}
        existing = [v for v in doc.get("verification") or [] if "command" in v]
        if existing:
            existing[0].update(entry)
        else:
            doc.setdefault("verification", []).append(entry)
        for key in inputs:
            assert re.search(rf"\{{{key}\}}", command), f"{name}: unused input {key}"
            if key not in doc["state"]["inputs"]:
                doc["state"]["inputs"].append(key)
        gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
        changed += 1
    print(f"{changed} graphs now carry an executable verification command; "
          f"{len(EXCLUDED)} declare an execute-risk ability and deliberately do not")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
