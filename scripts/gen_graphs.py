"""Instantiate top-priority catalog entries as AGR v1 graphs (pattern templates)."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# Curated top-50 (coverage-first: every domain represented, verifiability-weighted).
# code-review-pipeline already exists as a handcrafted graph and counts toward 50.
TOP50 = [
 "code-review-pipeline","bug-triage-and-fix","test-suite-generation","legacy-refactor",
 "dependency-upgrade","performance-optimization","release-notes-generation","docs-code-sync-audit",
 "incident-triage-router","runbook-executor","alert-noise-reduction","deploy-canary-verifier","postmortem-writer",
 "sql-generation-verified","etl-pipeline-builder","data-quality-audit","anomaly-investigation","ab-test-analysis",
 "literature-review-swarm","fact-check-pipeline","competitive-intelligence","citation-integrity-audit",
 "threat-intel-digest","phishing-triage","vuln-prioritization","soc-alert-investigation",
 "blog-production-pipeline","seo-optimization-loop","localization-pipeline",
 "meeting-to-actions","rfp-response-assembler","policy-compliance-check",
 "earnings-call-digest","kyc-document-processing","expense-audit-swarm",
 "contract-redline-pipeline","license-compliance-scan","ediscovery-triage",
 "clinical-literature-triage","medical-coding-audit","adverse-event-scanner",
 "quiz-generation-verified","essay-feedback-critic","rubric-grading-swarm",
 "ticket-triage-swarm","kb-article-generator","escalation-summarizer",
 "jd-drafting-critic","returns-triage","ux-research-synthesis",
]

def T(pattern: str) -> tuple[list, list, int]:
    """nodes, edges, max_steps for a pattern."""
    if pattern == "pipeline":
        return ([{"id": "intake", "speciality": "analyst", "abilities": ["analyze"]},
                 {"id": "produce", "speciality": "producer", "abilities": ["generate"]},
                 {"id": "review", "speciality": "critic", "abilities": ["critique"], "kind": "verifier"}],
                [{"from": "intake", "to": "produce"}, {"from": "produce", "to": "review"},
                 {"from": "review", "to": "produce", "when": "revision_requested and attempts < 2"}], 12)
    if pattern == "generator-critic":
        return ([{"id": "generate", "speciality": "producer", "abilities": ["generate"]},
                 {"id": "critique", "speciality": "critic", "abilities": ["critique"], "kind": "verifier"}],
                [{"from": "generate", "to": "critique"},
                 {"from": "critique", "to": "generate", "when": "rejected and attempts < 3"}], 10)
    if pattern == "debate":
        return ([{"id": "position-a", "speciality": "advocate", "abilities": ["generate"], "parallel_group": "debate"},
                 {"id": "position-b", "speciality": "advocate", "abilities": ["generate"], "parallel_group": "debate"},
                 {"id": "judge", "speciality": "judge", "abilities": ["adjudicate"], "kind": "verifier"}],
                [{"from": "position-a", "to": "judge"}, {"from": "position-b", "to": "judge"}], 8)
    if pattern == "router":
        return ([{"id": "route", "speciality": "dispatcher", "abilities": ["dispatch"], "kind": "router"},
                 {"id": "branch-simple", "speciality": "producer", "abilities": ["generate"]},
                 {"id": "branch-complex", "speciality": "producer", "abilities": ["generate"]},
                 {"id": "verify", "speciality": "critic", "abilities": ["critique"], "kind": "verifier"}],
                [{"from": "route", "to": "branch-simple", "when": "complexity <= moderate"},
                 {"from": "route", "to": "branch-complex", "when": "complexity > moderate"},
                 {"from": "branch-simple", "to": "verify"}, {"from": "branch-complex", "to": "verify"}], 12)
    if pattern == "map-reduce":
        return ([{"id": "partition", "speciality": "analyst", "abilities": ["analyze"]},
                 {"id": "map", "speciality": "mapper", "abilities": ["map_shard"], "parallel_group": "shards"},
                 {"id": "reduce", "speciality": "reducer", "abilities": ["reduce_merge"], "kind": "verifier"}],
                [{"from": "partition", "to": "map"}, {"from": "map", "to": "reduce"}], 20)
    if pattern == "parallel-swarm":
        return ([{"id": "plan", "speciality": "planner", "abilities": ["decompose_goal"]},
                 {"id": "work", "speciality": "worker", "abilities": ["run_command", "edit_files"], "parallel_group": "swarm"},
                 {"id": "verify", "speciality": "verifier", "abilities": ["run_command"], "kind": "verifier"}],
                [{"from": "plan", "to": "work"}, {"from": "work", "to": "verify"},
                 {"from": "verify", "to": "work", "when": "verify_failed and attempts < 3"}], 30)
    if pattern == "planner-executor-verifier":
        return ([{"id": "plan", "speciality": "planner", "abilities": ["decompose_goal"]},
                 {"id": "execute", "speciality": "executor", "abilities": ["execute_step"]},
                 {"id": "verify", "speciality": "verifier", "abilities": ["run_command"], "kind": "verifier"}],
                [{"from": "plan", "to": "execute"}, {"from": "execute", "to": "verify"},
                 {"from": "verify", "to": "execute", "when": "verify_failed and attempts < 3"}], 25)
    if pattern == "loop":
        return ([{"id": "attempt", "speciality": "producer", "abilities": ["generate"]},
                 {"id": "measure", "speciality": "evaluator", "abilities": ["evaluate"], "kind": "verifier"}],
                [{"from": "attempt", "to": "measure"},
                 {"from": "measure", "to": "attempt", "when": "below_target and attempts < 5"}], 15)
    raise ValueError(pattern)


def main() -> None:
    catalog = yaml.safe_load((ROOT / "usecases" / "catalog.yaml").read_text())
    by_name = {e["name"]: e for e in catalog["entries"]}
    existing = {p.parent.name for p in (ROOT / "graphs").glob("*/*/graph.yaml")}
    written = 0
    for name in TOP50:
        if name in existing:
            continue
        e = by_name[name]
        nodes, edges, max_steps = T(e["pattern"])
        doc = {"apiVersion": "agr/v1", "name": e["name"],
               "description": e["summary"], "category": e["domain"],
               "nodes": nodes, "edges": edges,
               "termination": {"max_steps": max_steps, "contract": e["verification"]},
               "verification": [{"assert": e["verification"]}]}
        out = ROOT / "graphs" / e["domain"] / e["name"] / "graph.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(doc, sort_keys=False, width=120))
        written += 1
    total = len(list((ROOT / "graphs").glob("*/*/graph.yaml")))
    print(f"wrote {written} graphs; total now {total}")

if __name__ == "__main__":
    main()
