"""Generate the eval scoreboard: re-run every graph's golden cases (rewriting
graphs/<domain>/<name>/profile.json) and splice a deterministic markdown table
into README.md between the scoreboard markers.

Source of truth is the eval harness itself (via `eval_graph`), not whatever
happens to be on disk in profile.json — so the scoreboard can never drift from
the current graph.yaml / cases.yaml. Run this after any graph or case change,
then commit the (possibly updated) profile.json files alongside README.md.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenticgraphs.evalcmd import eval_graph  # noqa: E402
from agenticgraphs.registry import ROOT, iter_graphs, load  # noqa: E402

BEGIN, END = "<!-- scoreboard:begin -->", "<!-- scoreboard:end -->"


def row_for(gpath: Path) -> dict:
    doc = load(gpath)
    name, category = doc["name"], doc["category"]
    has_cases = (ROOT / "evals" / name / "cases.yaml").exists()
    if not has_cases:
        return {"name": name, "category": category, "cases": 0, "pass_rate": None,
                "mean_steps": None, "routes": 0, "depth": "none", "live": None}
    profile = eval_graph(name)
    measured = profile["measured"]
    results = measured["results"]
    routes = len({tuple(r["trace"]) for r in results})
    return {
        "name": name,
        "category": category,
        "cases": measured["cases"],
        "pass_rate": measured["pass_rate"],
        "mean_steps": measured["mean_steps"],
        "routes": routes,
        "depth": measured["verification_depth"],
        "live": profile.get("measured_live"),
    }


def scoreboard_block(rows: list[dict]) -> str:
    with_cases = [r for r in rows if r["cases"]]
    total_cases = sum(r["cases"] for r in with_cases)
    depth_counts = Counter(r["depth"] for r in with_cases)
    lived = [r for r in with_cases if r["live"]]
    live_pass = sum(1 for r in lived if r["live"]["pass_rate"] == 1.0)
    fully_passing = sum(1 for r in with_cases if r["pass_rate"] == 1.0)
    lines = [
        BEGIN,
        "## 📊 Eval scoreboard",
        "",
        f"{len(with_cases)}/{len(rows)} graphs have golden eval cases "
        f"({total_cases} cases total, {fully_passing}/{len(with_cases)} graphs at 100% pass rate). "
        "Regenerate with `uv run python scripts/gen_scoreboard.py`.",
        "",
        "**Read the Depth column before the Pass rate column.** A 100% pass rate at "
        "`assert-fixture` means the assert held against a mock fixture written alongside "
        "the graph — it proves the graph routes the value through, not that the claim was "
        "earned. Depth grades, weakest first:",
        "",
        "| Depth | What actually happened |",
        "|---|---|",
        "| `describe-only` | prose; nothing machine-checked |",
        f"| `assert-fixture` | assert held against a mock fixture — **{depth_counts.get('assert-fixture', 0)} of "
        f"{len(with_cases)} graphs sit here** |",
        "| `assert-live` | assert held against real model output (`agr eval --live`) |",
        "| `command` | an executable check ran and exited 0 (`agr eval --run-commands`) |",
        "",
        f"**Real-model evidence:** {len(lived)} graphs carry a checked-in recording of an "
        f"actual model run (`evals/<graph>/live/`), and **{live_pass} of {len(lived)}** satisfy "
        "their contract against it. That column is reported separately, never blended into the "
        "headline pass rate — a contract a real model cannot satisfy must not be able to hide "
        "inside an average. Each cell shows the model and the date it was recorded; ⏳ marks a "
        "recording older than 90 days. Re-record with `scripts/record_live.py`."
        if lived else "",
        "",
        "| Graph | Domain | Cases | Pass rate | Depth | Live (real model) | Mean steps | Routes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda x: (x["category"], x["name"])):
        if r["cases"]:
            pass_rate = f"{r['pass_rate'] * 100:.0f}%"
            mean_steps = f"{r['mean_steps']:g}"
            routes = str(r["routes"])
        else:
            pass_rate = mean_steps = routes = "—"
        if r["live"]:
            lv = r["live"]
            stale = " ⏳" if lv.get("age_days", 0) > 90 else ""
            live_col = (("✅" if lv["pass_rate"] == 1.0 else "❌")
                        + f" {lv['runner'].split(':', 1)[-1]} · {lv.get('recorded', '?')}{stale}")
        else:
            live_col = "—"
        lines.append(f"| `{r['name']}` | {r['category']} | {r['cases'] or '—'} "
                     f"| {pass_rate} | `{r['depth']}` | {live_col} | {mean_steps} | {routes} |")
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    rows = [row_for(gpath) for gpath in iter_graphs()]
    missing = [r["name"] for r in rows if not r["cases"]]
    if missing:
        print(f"WARN no golden cases for: {', '.join(missing)}")
    block = scoreboard_block(rows)
    readme = ROOT / "README.md"
    text = readme.read_text()
    if BEGIN in text:
        pre, rest = text.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        text = pre + block + post
    else:
        anchor = "<!-- graph-of-graphs:end -->"
        if anchor in text:
            text = text.replace(anchor, anchor + "\n\n" + block, 1)
        else:
            anchor = "## 🚀 Getting Started"
            text = text.replace(anchor, block + "\n\n" + anchor, 1)
    readme.write_text(text)
    print(f"wrote scoreboard for {len(rows)} graphs ({len(rows) - len(missing)} with cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
