"""Give each remaining clone the structure its domain actually needs.

`gen_clone_report.py` measures how many of the registry's graphs are the same
graph once the free strings are stripped. It was 36 of 83; after v1.8's contract
work it was 17, in eight clusters of three-node chains and one shared router.

The fix is not to rename anything. Each cluster is differentiated by adding a
node or an edge the domain genuinely requires and the shared shape could not
express — a step whose absence was a real modelling gap, not a cosmetic one.
Where a domain needs no extra step, the honest answer is that it is the same
motif and belongs in `motifs/`, not that it deserves a decorative node.

Each change below names the gap it closes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import cases_path, load

#: graph -> (why, [nodes to insert], [edges to add], [edges to drop], {case outputs})
CHANGES: dict[str, dict] = {
    # A redline is a negotiation position, so the playbook lookup is a real step:
    # without it the drafter invents an acceptable fallback instead of retrieving
    # the one the business already agreed to.
    "contract-redline-pipeline": {
        "insert_after": "intake",
        "node": {"id": "playbook-lookup", "speciality": "researcher", "abilities": ["web_search"],
                 "inputs": ["summary"], "outputs": ["playbook_positions"],
                 "criteria": "Each flagged clause is matched to the playbook position that "
                             "governs it, including the fallback the business has already "
                             "agreed to accept. A clause with no retrieved position is "
                             "escalated, not negotiated from first principles."},
        "case": {"playbook_positions": [{"clause": "indemnity", "position": "mutual"}]},
    },
    # KYC is not only extraction: a customer whose details are correct and whose
    # name is on a sanctions list must still be stopped, and no amount of careful
    # field-reading finds that. `parallel_group` is deliberately NOT set — a group
    # of one is a label standing in for fan-out, which `test_v12` refuses; the
    # fan-out here is the edge structure, not an annotation.
    "kyc-document-processing": {
        "insert_after": "intake",
        "node": {"id": "sanctions-screen", "speciality": "screener", "abilities": ["screen"],
                 "inputs": ["summary"], "outputs": ["screen_hits"],
                 "criteria": "Every name and date of birth is screened against the sanctions "
                             "and PEP lists for the customer's jurisdiction. A near-match is "
                             "a hit to adjudicate, never a miss to round away."},
        "case": {"screen_hits": []},
    },
    # Compliance is per-clause: one verdict for a whole document cannot say which
    # clause failed, which is the only thing the reader needs.
    "policy-compliance-check": {
        "insert_after": "intake",
        "node": {"id": "clause-map", "speciality": "mapper", "abilities": ["map_shard"],
                 "inputs": ["summary"], "outputs": ["clause_shards"],
                 "criteria": "Each policy clause becomes its own shard with the document "
                             "spans that could satisfy or breach it, so a finding can name a "
                             "clause id rather than a document."},
        "case": {"clause_shards": [{"clause_id": "C-1", "spans": ["s1"]}]},
    },
    # An outline is where a post's argument is decided; merging it into drafting
    # is how a pipeline produces fluent text that argues nothing.
    "blog-production-pipeline": {
        "insert_after": "intake",
        "node": {"id": "outline", "speciality": "planner", "abilities": ["decompose_goal"],
                 "inputs": ["summary"], "outputs": ["outline"],
                 "criteria": "The outline states the claim each section makes and the evidence "
                             "it will use, so the draft has an argument to write rather than a "
                             "topic to fill."},
        "case": {"outline": [{"section": "why", "claim": "c", "evidence": "e"}]},
    },
    # A KB article is only useful if it is found. Dedupe against the existing base
    # is a step, not a judgement the writer can make while writing.
    "kb-article-generator": {
        "insert_after": "intake",
        "node": {"id": "dedupe-search", "speciality": "researcher", "abilities": ["web_search"],
                 "inputs": ["summary"], "outputs": ["existing_articles"],
                 "criteria": "The existing knowledge base is searched for the same symptom "
                             "before anything is written. A near-duplicate is an article to "
                             "update, not a second article to publish."},
        "case": {"existing_articles": []},
    },
    # A swarm fans out. This one had two EXCLUSIVE branches, which is a router —
    # the same graph as `incident-triage-router` wearing the word "swarm". Sentiment
    # now runs alongside whichever complexity branch fires, expressed as edges;
    # `parallel_group` is not set, because a group of one is a label standing in for
    # fan-out and `test_v12` exists to refuse exactly that.
    "ticket-triage-swarm": {
        "insert_after": "route",
        "node": {"id": "branch-sentiment", "speciality": "analyst", "abilities": ["analyze"],
                 "inputs": ["complexity"], "outputs": ["assigned_queue"],
                 "criteria": "Sentiment is assessed independently of complexity, because an "
                             "angry customer with a simple problem and a calm one with an "
                             "outage need different queues and the routing rule cannot see "
                             "both from one classification."},
        "case": {"assigned_queue": "billing-tier2"},
        "extra_edges": [{"from": "branch-sentiment", "to": "verify"}],
        "edge_from_source": "route",
    },
    # SQL is checkable by running it. A critic that reads a query and judges it
    # plausible is doing something categorically weaker than executing it.
    "sql-generation-verified": {
        "insert_after": "generate",
        "node": {"id": "execute", "speciality": "executor",
                 "abilities": ["execute_step", "run_command"],
                 "inputs": ["draft"], "outputs": ["row_count", "exit_code"],
                 "criteria": "The query is run against the real schema and its exit code and "
                             "row count are recorded. A query judged correct without being "
                             "executed has not been verified."},
        "case": {"row_count": 12, "exit_code": 0},
    },
    # The critic must solve the item WITHOUT the key, so the key cannot reach it
    # on the same edge as the item. That separation is the whole method.
    "quiz-generation-verified": {
        "insert_after": "generate",
        "node": {"id": "blind-solve", "speciality": "worker", "abilities": ["run_command"],
                 "inputs": ["draft"], "outputs": ["blind_answers"],
                 "criteria": "Each item is answered without sight of the key. An answer "
                             "produced by a step that could see the key measures nothing about "
                             "whether the item is solvable."},
        "case": {"blind_answers": [{"item": 1, "answer": "b"}]},
    },
    # Screening comes before reading in every real review protocol; merging them
    # means the reader's time is spent on papers that should have been excluded.
    "literature-review-swarm": {
        "insert_after": "plan",
        "node": {"id": "screen", "speciality": "screener", "abilities": ["screen"],
                 "inputs": ["tasks"], "outputs": ["included", "excluded"],
                 "criteria": "Each paper is included or excluded against the stated criteria, "
                             "with the reason recorded. An unexplained exclusion cannot be "
                             "audited, which is the difference between a review and a reading "
                             "list."},
        "case": {"included": ["p1"], "excluded": [{"paper": "p2", "reason": "wrong design"}]},
    },
    # A coding audit that finds an error must say what the correct code was;
    # otherwise the finding is not actionable by the coder who has to fix it.
    "medical-coding-audit": {
        "insert_after": "work",
        "node": {"id": "recode", "speciality": "compensator",
                 "abilities": ["rollback", "backfill"],
                 "inputs": ["work_result"], "outputs": ["corrections"],
                 "criteria": "Every disputed code is paired with the code the documentation "
                             "does support, so the finding tells the coder what to change it "
                             "to rather than only that it is wrong."},
        "case": {"corrections": [{"from": "J18.9", "to": "J15.9"}]},
    },
    # A threat brief is about what to do, not what happened; the mapping from
    # advisory to the estate's own assets is the step that makes it actionable.
    "threat-intel-digest": {
        "insert_after": "map",
        "node": {"id": "estate-match", "speciality": "analyst", "abilities": ["analyze"],
                 "inputs": ["shard_result"], "outputs": ["affected_assets"],
                 "criteria": "Each advisory is matched against the estate actually run, so "
                             "severity is reported as exposure rather than as the vendor's "
                             "CVSS in isolation."},
        "case": {"affected_assets": [{"cve": "CVE-2026-1", "assets": ["api-1"]}]},
    },
}


def apply(name: str, spec: dict) -> None:
    gpath = find_graph(name)
    doc = load(gpath)
    anchor = spec["insert_after"]
    new = spec["node"]
    idx = next(i for i, n in enumerate(doc["nodes"]) if n["id"] == anchor)
    doc["nodes"].insert(idx + 1, new)

    if spec.get("extra_edges"):
        # A fan-out: the new node runs alongside the existing branches, not after.
        doc["edges"].append({"from": spec["edge_from_source"], "to": new["id"]})
        doc["edges"].extend(spec["extra_edges"])
    else:
        # Splice into the chain: anchor -> new -> whatever anchor fed.
        downstream = [e for e in doc["edges"] if e["from"] == anchor]
        for e in downstream:
            e["from"] = new["id"]
        doc["edges"].insert(idx + 1, {"from": anchor, "to": new["id"]})
        doc["edges"].sort(key=lambda e: [n["id"] for n in doc["nodes"]].index(e["from"]))

    gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))

    cpath = cases_path(name)
    data = yaml.safe_load(cpath.read_text())
    for case in data["cases"]:
        case["node_outputs"][new["id"]] = spec["case"]
    cpath.write_text(yaml.safe_dump(data, sort_keys=False, width=100))


def main() -> int:
    for name, spec in CHANGES.items():
        apply(name, spec)
    print(f"differentiated {len(CHANGES)} graphs by adding the step their domain requires")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
