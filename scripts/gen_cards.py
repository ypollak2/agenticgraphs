"""Generate per-graph CARD.md files, the CARDS.md index, and the README
"graph of graphs" block. Cards are derived from graph.yaml + usecases/catalog.yaml
so they cannot drift from the artifacts: edit those, then rerun this script.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.inspect import structural_profile, to_mermaid  # noqa: E402
from agenticgraphs.registry import ROOT, iter_graphs, load  # noqa: E402

CATALOG = ROOT / "usecases" / "catalog.yaml"
BEGIN, END = "<!-- graph-of-graphs:begin -->", "<!-- graph-of-graphs:end -->"

RATIONALE = {
    "tree-search": (
        "Candidates are branched, scored against a real measurement, and pruned to a beam — "
        "so the graph explores a space rather than committing to its first idea. This is "
        "beam search, not MCTS: no rollout policy and no learned value function, both of "
        "which need a real environment. What ships is whatever measurably won."
    ),
    "ensemble-quorum": (
        "Several independent passes answer the same question and a quorum decides. Because "
        "the passes cannot see each other, agreement is evidence and spread is a calibration "
        "signal. Dissent is reported alongside the verdict rather than averaged away, and a "
        "tie is surfaced as no-consensus instead of resolved by coin flip."
    ),
    "red-team-blue-team": (
        "An attacker searches for a working bypass while a defender patches, alternating "
        "until the attacker is exhausted. It is the only motif here that produces evidence "
        "of *absence*: the run ends because nothing more could be found, not because nobody "
        "looked."
    ),
    "reflexion": (
        "Each failed attempt writes down what was learned, and the next attempt reads it. "
        "A plain retry loop re-runs the same reasoning against the same inputs and fails the "
        "same way; this one narrows. Lessons are scoped memory, so what the graph learned is "
        "inspectable rather than buried in a context window."
    ),
    "blackboard": (
        "Specialists contribute independently to shared evidence and a controller decides "
        "when the picture is closed enough to act on. Suited to open-ended investigation, "
        "where the next useful question depends on what the last contributor found. Open "
        "questions are listed rather than quietly dropped."
    ),
    "tournament": (
        "More than two options, judged pairwise on one rubric, with the winner recorded "
        "alongside the margin over the runner-up. A single debate collapses to two positions; "
        "a tournament keeps the field, and the recorded margin means the decision can be "
        "revisited on evidence instead of re-argued from scratch."
    ),
    "lifecycle": (
        "A multi-phase workflow where each phase is itself a motif and hand-offs are "
        "explicit. Phases that duplicate an existing single-purpose graph reference it "
        "with `kind: subgraph` instead of restating it, so the flat library becomes the "
        "component library and a fix to a child propagates to every composite using it."
    ),
    "human-gate": (
        "A `kind: human` node holds an approval contract that no model may sign — the "
        "live runner raises rather than approve its own work. Downstream flow edges stay "
        "blocked until the contract evaluates true, which is what makes a graph usable "
        "in a regulated domain instead of merely plausible-looking."
    ),
    "supervisor-hierarchy": (
        "A supervisor decomposes a goal and delegates each slice to a subordinate graph "
        "rather than to more nodes in its own topology. This buys depth without a "
        "forty-node flat blob: the parent reads as five phases, and each phase is "
        "independently testable and independently reusable."
    ),
    "saga": (
        "Every forward step that writes has a paired compensator reachable by a "
        "`kind: compensate` edge, so a failure unwinds to a consistent state instead of "
        "leaving the system half-migrated. Lint refuses a saga whose execute-risk step "
        "has no compensator — the failure mode is caught at author time, not in prod."
    ),
    "escalation-ladder": (
        "Tiers are attempted cheapest-first, each with an explicit exit test, and the "
        "ladder terminates at a human rather than at a confident guess. Cost tracks the "
        "difficulty of each item, and the honest floor means an ambiguous case is "
        "escalated rather than resolved by whichever tier ran out of ideas."
    ),
    "pipeline": (
        "Staged specialists each own one narrow concern, so quality problems are "
        "localized to the stage that produced them instead of being smeared across a "
        "single mega-prompt. Output only leaves the graph through the exit contract."
    ),
    "parallel-swarm": (
        "Independent workers cover disjoint slices of the input at the same time. "
        "Because they cannot see each other's drafts, agreement is evidence and "
        "disagreement surfaces blind spots; the aggregator merges with explicit rules. "
        "Wall-clock time is roughly the slowest worker, not the sum."
    ),
    "router": (
        "A cheap classifier sends every item down the narrowest branch that can handle "
        "it, so cost and latency scale with the difficulty of each item rather than the "
        "worst case. Escalation edges guarantee hard items still reach the strong path."
    ),
    "generator-critic": (
        "The generator optimizes for recall, the critic for precision. Nothing is "
        "accepted until the critic signs off, which filters out trivial, tautological, "
        "or hallucinated output before it ever reaches you."
    ),
    "planner-executor-verifier": (
        "The plan makes intent inspectable before anything touches the world, the "
        "executor works inside that plan, and the verifier proves the postcondition "
        "actually holds — success is demonstrated, not asserted."
    ),
    "map-reduce": (
        "Work fans out over shards and the reduce step merges with explicit dedupe and "
        "conflict rules, so throughput scales with shard count while the output stays "
        "a single consistent artifact."
    ),
    "loop": (
        "A bounded improve-and-measure cycle: each iteration must beat the last "
        "measured score or the loop exits. `max_steps` is a hard cap, so the graph can "
        "refine but never wander."
    ),
    "debate": (
        "Adversarial positions force every claim to survive counter-argument before a "
        "judge selects with cited evidence — a structural antidote to sycophancy and "
        "single-model anchoring."
    ),
}

SHAPE_LEGEND = "Legend: `[/…/]` router · `{{…}}` verifier · `[…]` worker/agent node."


def card_id(entry: dict) -> str:
    return "AGR-" + entry["id"].split("-", 1)[1]


def gen_card(doc: dict, entry: dict, catalog: list[dict], has_evals: bool) -> str:
    name, cat = doc["name"], doc["category"]
    prof = structural_profile(doc)["structural"]
    cid = card_id(entry)
    lines = [
        "<!-- generated by scripts/gen_cards.py — edit graph.yaml / usecases/catalog.yaml, then `uv run python scripts/gen_cards.py` -->",
        f"# 🪪 {cid} · `{name}`",
        "",
        f"> {doc['description']}",
        "",
        f"| Card ID | Domain | Pattern | Nodes | Edges | Verifiers | Routers | Max steps | Risk surface |",
        f"|---|---|---|---|---|---|---|---|---|",
        f"| `{cid}` | {cat} | **{entry['pattern']}** | {prof['nodes']} | {prof['edges']} "
        f"| {prof['verifier_nodes']} | {prof['router_nodes']} | {prof['max_steps']} | {prof['risk_surface']} |",
        "",
        "## The graph",
        "",
        "```mermaid",
        to_mermaid(doc),
        "```",
        "",
        SHAPE_LEGEND,
        "",
        "## What it does",
        "",
        entry["summary"],
        "",
        "## Why it should deliver results",
        "",
        RATIONALE[entry["pattern"]],
        "",
        f"- **Exit contract** — {doc['termination']['contract']}",
    ]
    for v in doc.get("verification", []):
        if "assert" in v:
            lines.append(f"- **Machine-checked** — `{v['assert']}`")
        elif "command" in v:
            lines.append(f"- **Command-checked** — `{v['command']}`")
    lines.append(f"- **Bounded** — hard stop after {prof['max_steps']} steps"
                 + ("; every loop edge is condition-guarded" if prof["loops"] else "; the topology is acyclic"))
    if has_evals:
        lines.append(f"- **Golden cases** — `uv run agr eval {name}` replays recorded cases "
                     "through the real edge/assert logic (mock runner proves mechanics; `--live` measures your model)")
        lines.append(f"- **Trace gallery** — [every case's route, node outputs, and checked asserts]"
                     f"(../../../docs/traces/{name}.md)")
    else:
        lines.append("- **Gate-checked** — schema + lint + structural gate run in CI; golden eval cases are the "
                     "next step for this card (see `evals/` for the format)")
    lines += [
        "",
        "## How to work with it",
        "",
        "```bash",
        f"uv run agr show {name}       # full definition",
        f"uv run agr profile {name}    # deterministic structural facts",
        f"uv run agr mermaid {name}    # regenerate the diagram below",
    ]
    if has_evals:
        lines.append(f"uv run agr eval {name}       # run golden cases (add --live for your endpoint)")
    lines += [
        f"uv run agr adapt {name} --target langgraph > app.py   # compile to runnable LangGraph",
        f"uv run agr optimize {name}   # propose bounded structural improvements (dry-run)",
        "```",
        "",
        "Over MCP: `uv run agr mcp` exposes the registry (search / show / profile) to any MCP client.",
        "To evolve it: `uv run agr infuse " + name + " <node> <ability>` — every mutation is gate-checked "
        "and appended to the graph's lineage log.",
        "",
        "## Node roster",
        "",
        "| Node | Speciality | Kind | Abilities |",
        "|---|---|---|---|",
    ]
    for n in doc["nodes"]:
        lines.append(f"| `{n['id']}` | {n['speciality']} | {n.get('kind', 'agent')} "
                     f"| {', '.join(n.get('abilities', [])) or '—'} |")
    lines += ["", "## Edge logic", "", "| From | To | Condition |", "|---|---|---|"]
    for e in doc["edges"]:
        lines.append(f"| `{e['from']}` | `{e['to']}` | {e.get('when', 'always')} |")

    shipped = {g.parent.name for g in iter_graphs()}
    same_dom = [e for e in catalog if e["domain"] == cat and e["name"] != name and e["name"] not in shipped]
    same_pat = [e for e in catalog if e["pattern"] == entry["pattern"] and e["domain"] != cat
                and e["name"] not in shipped]
    picks = (same_dom + same_pat)[:5]
    if picks:
        lines += ["", "## Optional use-cases", "",
                  "Adjacent entries from the use-case catalog this card adapts to with small edits:", ""]
        for e in picks:
            lines.append(f"- **{e['name']}** ({e['domain']}, {e['pattern']}) — {e['summary']} "
                         f"*Verify:* {e['verification']}.")
    lines += ["", "---", f"*Regenerate: `uv run python scripts/gen_cards.py` · Index: [CARDS.md](../../../CARDS.md)*", ""]
    return "\n".join(lines)


def gen_index(rows: list[dict]) -> str:
    lines = [
        "<!-- generated by scripts/gen_cards.py — do not edit by hand -->",
        "# 🗂️ Graph cards",
        "",
        f"{len(rows)} shipped graphs, each with a full card: what it does, why it delivers, "
        "how to run/adapt/evolve it, and the diagram.",
        "",
    ]
    by_dom: dict[str, list[dict]] = {}
    for r in rows:
        by_dom.setdefault(r["domain"], []).append(r)
    for dom in sorted(by_dom):
        lines += [f"## {dom}", "", "| Card | Graph | Pattern | Contract |", "|---|---|---|---|"]
        for r in sorted(by_dom[dom], key=lambda x: x["cid"]):
            lines.append(f"| `{r['cid']}` | [{r['name']}]({r['path']}) | {r['pattern']} | {r['contract']} |")
        lines.append("")
    return "\n".join(lines)


def graph_of_graphs(rows: list[dict]) -> str:
    from collections import Counter
    pat = Counter(r["pattern"] for r in rows)
    dom = Counter(r["domain"] for r in rows)
    example = {}
    for r in sorted(rows, key=lambda x: x["cid"]):
        example.setdefault(r["pattern"], r["name"])
    g = ["```mermaid", "flowchart TD",
         f'    ROOT(("🕸️ agenticgraphs<br/>{len(rows)} graphs · {len(dom)} domains"))']
    for i, (p, c) in enumerate(pat.most_common()):
        g.append(f'    ROOT --> P{i}[/"{p} ×{c}"/]')
        g.append(f'    P{i} --> E{i}["e.g. {example[p]}"]')
    g.append("```")
    pie = ["```mermaid", 'pie showData title Graphs per domain']
    for d, c in dom.most_common():
        pie.append(f'    "{d}" : {c}')
    pie.append("```")
    return "\n".join([
        BEGIN,
        "## 🗺️ The graph of graphs",
        "",
        "Every shipped graph is one of nineteen verified motifs. Full per-graph cards "
        "(diagram, contract, node roster, use-cases) live in [CARDS.md](CARDS.md).",
        "",
        *g, "",
        "<details><summary>Distribution by domain</summary>", "",
        *pie, "",
        "</details>",
        END,
    ])


def main() -> int:
    catalog = yaml.safe_load(CATALOG.read_text())["entries"]
    by_name = {e["name"]: e for e in catalog}
    rows = []
    for gpath in iter_graphs():
        doc = load(gpath)
        entry = by_name.get(doc["name"])
        if entry is None:
            print(f"FAIL no catalog entry for {doc['name']}"); return 1
        has_evals = (ROOT / "evals" / doc["name"] / "cases.yaml").exists()
        (gpath.parent / "CARD.md").write_text(gen_card(doc, entry, catalog, has_evals))
        rows.append({"cid": card_id(entry), "name": doc["name"], "domain": doc["category"],
                     "pattern": entry["pattern"], "contract": doc["termination"]["contract"],
                     "path": f"graphs/{doc['category']}/{doc['name']}/CARD.md"})
    (ROOT / "CARDS.md").write_text(gen_index(rows) + "\n")
    readme = ROOT / "README.md"
    text = readme.read_text()
    block = graph_of_graphs(rows)
    if BEGIN in text:
        pre, rest = text.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        text = pre + block + post
    else:
        anchor = "## 🚀 Getting Started"
        text = text.replace(anchor, block + "\n\n" + anchor, 1)
    readme.write_text(text)
    print(f"wrote {len(rows)} cards + CARDS.md + README block")
    return 0


if __name__ == "__main__":
    sys.exit(main())
