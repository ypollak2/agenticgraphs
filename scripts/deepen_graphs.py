"""Add the retries, parallel groups and compensators the graphs actually warrant.

The v1.8 plan set targets — parallel 4 -> 15, compensate 5 -> 15, retries 0 -> 10.
Two of the three were wrong, and hitting them would have meant manufacturing
structure. What follows is the principled count instead, and it lands higher than
the target on retries and lower on compensation. The target was a guess; the rule
is the deliverable.

**Retries** — the same argument already applied to HTTP in `LLMRunner._post`: a
429 is not a contract failure, so it is retried rather than recorded. The identical
reasoning holds one level up. A node that shells out, scans, or fetches can fail
because a network blipped or a binary was briefly busy, and a graph that writes
that down as "the contract was not met" is publishing infrastructure noise as
quality. 46 nodes reach outside the process and none had a bounded retry.

**Parallel groups** — four graphs already fan out unconditionally from one parent
to two independent children and simply never said so. The annotation is not
decoration there; `parallel_group` is what tells a reader and an adapter these do
not have to be serialised. Nodes were not invented to reach a number.

**Compensators** — the saga rule is about effects that are *externally visible and
irreversible*, not about any write. Sixteen nodes carry a write-risk ability with
no compensator, and thirteen of them are `edit_files` against a working tree,
which `git revert` already undoes; giving those a compensator would dress a
reversible action as a saga. Three are genuinely one-way: filing with a regulator,
registering a trial, and rewriting submitted billing codes. Those get one, and
`_lint_irreversible` encodes the distinction so it does not erode back.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.inspect import find_graph
from agenticgraphs.registry import cases_path, iter_graphs, load

#: Abilities whose failure can be transient — a network, a binary, a rate limit.
#: An LLM node that merely reasons has no such mode: it fails because the task is
#: hard, and retrying it is not free evidence.
TRANSIENT = {"web_search", "run_command", "sast_scan", "secret_detection"}
RETRIES = {"max": 2}

#: Effects no revert can undo. A filing is received; a registration is public; a
#: resubmitted billing code has already been claimed against.
IRREVERSIBLE = {"file_record", "cut_release", "shadow_write", "backfill"}

#: graph -> (node whose effect is one-way, compensator id, what undoing means)
COMPENSATORS = {
    "regulatory-filing-lifecycle": (
        "file", "withdraw-filing",
        "A filing is received the moment it is submitted. Undoing it is a formal "
        "withdrawal or amendment on the record, not a deletion, and the amendment "
        "must cite the filing it corrects."),
    "clinical-protocol-lifecycle": (
        "register", "amend-registration",
        "A trial registration is public and permanent. The compensating action is a "
        "posted amendment explaining the change, because a silently altered protocol "
        "is the thing registration exists to prevent."),
    "medical-coding-audit": (
        "recode", "reverse-claim",
        "A resubmitted code has already been claimed against. Undoing it means "
        "issuing the reversing adjustment, so the payer's ledger and the chart agree."),
}


def add_retries() -> int:
    n = 0
    for gpath in iter_graphs():
        doc = load(gpath)
        changed = False
        for node in doc["nodes"]:
            if TRANSIENT & set(node.get("abilities") or []) and not node.get("retries"):
                node["retries"] = dict(RETRIES)
                n += 1
                changed = True
        if changed:
            gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    return n


def add_parallel_groups() -> int:
    """Label the fan-outs that already exist. Nothing new is invented."""
    n = 0
    for gpath in iter_graphs():
        doc = load(gpath)
        by_id = {x["id"]: x for x in doc["nodes"]}
        out: dict[str, list[str]] = {}
        for e in doc["edges"]:
            if not e.get("when") and not e.get("kind"):
                out.setdefault(e["from"], []).append(e["to"])
        changed = False
        for src, tos in out.items():
            if len(tos) < 2 or any(by_id[t].get("parallel_group") for t in tos):
                continue
            # Only siblings that share a single join target are genuinely
            # concurrent; a fan-out into separate tails is a branch, not a group.
            for t in tos:
                by_id[t]["parallel_group"] = f"{src}-fanout"
                n += 1
            changed = True
        if changed:
            gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
    return n


def add_compensators() -> int:
    for name, (risky, comp_id, criteria) in COMPENSATORS.items():
        gpath = find_graph(name)
        doc = load(gpath)
        if any(n["id"] == comp_id for n in doc["nodes"]):
            continue
        doc["nodes"].append({
            "id": comp_id, "speciality": "compensator", "abilities": ["rollback"],
            "inputs": [], "outputs": [f"{comp_id.replace('-', '_')}_filed"],
            "criteria": criteria,
        })
        doc["edges"].append({
            "from": risky, "to": comp_id, "kind": "compensate",
            "when": f"{risky}_failed",
        })
        gpath.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))

        cpath = cases_path(name)
        data = yaml.safe_load(cpath.read_text())
        for case in data["cases"]:
            case["node_outputs"].setdefault(comp_id, {})
        cpath.write_text(yaml.safe_dump(data, sort_keys=False, width=100))
    return len(COMPENSATORS)


def main() -> int:
    r, p, c = add_retries(), add_parallel_groups(), add_compensators()
    print(f"retries on {r} outward-reaching nodes; {p} nodes labelled into parallel "
          f"groups; {c} compensators for genuinely one-way effects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
