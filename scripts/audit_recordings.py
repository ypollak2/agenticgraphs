"""Executable audit: is a checked-in recording still evidence about the graph it
is filed under?

A recording in a graph's `live/` stamps the model and the date. It does not
stamp the graph revision it was recorded against — so nothing detects a graph
edited after its evidence was captured, and `ReplayRunner` replays the old reply
against the new shape without comment.

This measures the gap the `graph_sha` marker is meant to close. Until recordings
carry that field, the revision each one saw is reconstructed from git: the commit
that last touched the recording file is the commit whose graph.yaml the model was
prompted with.

Four questions, weakest to sharpest:

  1. did graph.yaml change at all since the recording was committed?
  2. did the SHAPE change -- the parts that decide how a reply is replayed and
     graded? A reworded description invalidates nothing.
  3. did the VERDICT change? Same recording bytes, graded at its own commit and
     graded at HEAD. A flip means checked-in evidence changed meaning after the
     fact, which is the finding this audit exists for.
  4. does any PUBLISHED evidence tier depend on a recording from (2)?

Exits non-zero when any verdict has flipped (question 3), because that is the
case where the scoreboard is reporting something no model was ever asked.

    uv run python scripts/audit_recordings.py [--json reports/out.json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# `shape` and `sha` live in the registry core, not here: which parts of a graph a
# recording depends on is a fact about the registry, and a second copy in a script
# is exactly the duplication M11 exists to remove.
from agenticgraphs.registry import live_dir, sha, shape

ROOT = Path(__file__).resolve().parents[1]


def git(*a: str) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True,
                          text=True, check=False).stdout


def _verdicts(text: str) -> dict:
    """(case, model) -> [verdict, ...] in file order.

    A list, not a scalar: a cell can hold several samples of the same case on the
    same model, and on a flaky cell they disagree with each other. Collapsing them
    into one key would let sample ordering masquerade as a verdict change — the
    first draft of this audit did exactly that and reported a flip on
    `hiring-lifecycle` that was nothing but a dict overwrite.
    """
    try:
        lv = (json.loads(text).get("measured_live") or {})
    except json.JSONDecodeError:
        return {}
    out: dict[tuple, list[bool]] = defaultdict(list)
    for r in lv.get("results", []):
        out[(r.get("id"), r.get("model"))].append(bool(r.get("passed")))
    return dict(out)


def _tier(results: list[dict]) -> str | None:
    if not results:
        return None
    by_model = defaultdict(list)
    for r in results:
        by_model[r.get("model")].append(bool(r.get("passed")))
    rates = {m: sum(v) / len(v) for m, v in by_model.items()}
    if all(x == 0 for x in rates.values()):
        return "unsatisfiable"
    if any(len(set(v)) > 1 for v in by_model.values()):
        return "flaky"
    if len(set(rates.values())) > 1:
        return "models-disagree"
    if all(x == 1.0 for x in rates.values()):
        return "satisfied-all"
    return "partial"


def audit() -> dict:
    graphs, profiles, head_full, head_shape = {}, {}, {}, {}
    for p in sorted(ROOT.glob("graphs/*/*/graph.yaml")):
        doc = yaml.safe_load(p.read_text())
        graphs[doc["name"]] = str(p.relative_to(ROOT))
        profiles[doc["name"]] = str((p.parent / "profile.json").relative_to(ROOT))
        head_full[doc["name"]] = sha(doc)
        head_shape[doc["name"]] = sha(shape(doc))

    rows, blob_cache, verdict_cache, head_verdicts = [], {}, {}, {}
    # Through the registry, not a glob: where recordings live is the registry's
    # business, and this audit must keep working either side of the bundle move.
    for name in sorted(graphs):
        for r in sorted(live_dir(name, ROOT).glob("*.json")):
            rel = str(r.relative_to(ROOT))
            # Ask about the bundle path AND the pre-move `evals/` path, and take
            # the last commit that Added or Modified either. `--diff-filter=AM`
            # skips the move itself, which renamed 560 files without changing a
            # byte any model produced.
            #
            # Explicitly NOT `--follow`, which was tried and is wrong here: its
            # similarity heuristic hops onto a near-identical file's history, so
            # a `#1` resample gets dated to the older sample it resembles. That
            # reported 139 stale recordings against a true 71. The two-pathspec
            # form reproduces the pre-move measurement on all 560, exactly.
            #
            # And this is the case for the `graph_sha` stamp in one paragraph: a
            # file move, not even an edit, first made git-reconstructed
            # provenance report zero recordings, then nearly doubled the finding.
            # A hash written at capture would not have noticed the move at all.
            legacy = f"evals/{name}/live/{r.name}"
            commit = git("log", "-1", "--format=%H", "--diff-filter=AM",
                         "--", rel, legacy).strip()
            if not commit:
                continue
            key = (commit, name)
            if key not in blob_cache:
                blob = git("show", f"{commit}:{graphs[name]}")
                old = yaml.safe_load(blob) if blob.strip() else None
                blob_cache[key] = (sha(old), sha(shape(old))) if old else None
                verdict_cache[key] = _verdicts(git("show", f"{commit}:{profiles[name]}"))
            if name not in head_verdicts:
                head_verdicts[name] = _verdicts((ROOT / profiles[name]).read_text())

            rec = json.loads(r.read_text())
            model, case = rec.get("model", "?"), r.stem.split("@")[0]
            old_hashes = blob_cache[key]
            content = "absent" if not old_hashes else (
                "same" if old_hashes[0] == head_full[name] else "changed")
            shp = "absent" if not old_hashes else (
                "same" if old_hashes[1] == head_shape[name] else "changed")
            # Only a cell holding exactly ONE sample on both sides can be compared:
            # with several samples the pairing between a recording file and a result
            # row is not recoverable from the profile, and a re-record may legitimately
            # have added samples. Conservative on purpose — a false flip would be worse
            # than a missed one, since the whole point is to say what the evidence is
            # actually worth.
            then = verdict_cache[key].get((case, model)) or []
            now = head_verdicts[name].get((case, model)) or []
            if len(then) != 1 or len(now) != 1:
                verdict = "not-comparable"
            elif then[0] == now[0]:
                verdict = "stable"
            else:
                verdict = f"{'PASS' if then[0] else 'FAIL'}->{'PASS' if now[0] else 'FAIL'}"
            rows.append({"graph": name, "file": rel, "model": model, "case": case,
                         "commit": commit[:8], "content": content, "shape": shp,
                         "verdict": verdict})

    stale = {(x["graph"], x["model"], x["case"]) for x in rows if x["shape"] == "changed"}
    tier_now, tier_excl, moved = Counter(), Counter(), []
    for name, rel in profiles.items():
        res = (json.loads((ROOT / rel).read_text()).get("measured_live") or {}).get("results", [])
        kept = [r for r in res if (name, r.get("model"), r.get("id")) not in stale]
        a, b = _tier(res), _tier(kept)
        tier_now[a] += 1
        tier_excl[b] += 1
        if a != b:
            moved.append({"graph": name, "published": a, "without_stale": b,
                          "dropped": len(res) - len(kept)})
    return {"rows": rows, "tier_published": dict(tier_now),
            "tier_without_stale": dict(tier_excl), "tier_moved": moved}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, help="also write the full row-level result here")
    args = ap.parse_args()

    res = audit()
    rows = res["rows"]
    changed = [r for r in rows if r["content"] == "changed"]
    shaped = [r for r in rows if r["shape"] == "changed"]
    flips = [r for r in rows if r["verdict"] not in ("stable", "not-comparable")]

    print(f"recordings: {len(rows)}")
    print(f"1. graph.yaml changed since the recording:   {len(changed):4d}"
          f"  ({len(changed) / len(rows) * 100:.0f}%)")
    print(f"2. SHAPE changed (evidence is stale):        {len(shaped):4d}"
          f"  ({len(shaped) / len(rows) * 100:.0f}%)")
    print(f"3. VERDICT flipped without re-recording:     {len(flips):4d}")
    for f in sorted(flips, key=lambda x: (x["graph"], x["model"])):
        print(f"     {f['graph']:36s} {f['model']:18s} {f['case']:26s} {f['verdict']}")

    print("\n   stale recordings by model:")
    for m, c in Counter(r["model"] for r in shaped).most_common():
        tot = sum(1 for r in rows if r["model"] == m)
        print(f"     {m:22s} {c:4d} / {tot:4d}")

    print(f"\n4. published tier depends on a stale recording: "
          f"{len(res['tier_moved'])} graphs")
    for m in sorted(res["tier_moved"], key=lambda x: x["graph"]):
        print(f"     {m['graph']:36s} {m['published']:16s} -> {m['without_stale']}")
    print(f"\n   tier counts   published: {res['tier_published']}")
    print(f"   excluding stale evidence: {res['tier_without_stale']}")
    print("\n   Excluding is NOT the corrected number: dropping a stale row removes a "
          "\n   model from that graph's denominator entirely. These need re-recording, "
          "\n   not exclusion.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(res, indent=2))
        print(f"\nwrote {args.json}")

    print("\nAUDIT " + ("FAILED" if flips else "PASSED"))
    return 1 if flips else 0


if __name__ == "__main__":
    sys.exit(main())
