"""The registry core: locate, load, and **join** AGR artifacts.

Until M11 this module answered one question — *where are the files* — and every
consumer answered the rest for itself. What a graph *is* was reassembled
independently by the CLI, the MCP server, and six scripts in `scripts/`: the same
graph.yaml + profile.json + cases.yaml + catalog-entry join, written six times,
drifting six ways.

`RegistryEntry` is that join, once. `Registry.load()` builds every entry (83
graphs, ~80 ms) and everything above this module reads entries instead of globbing.

One graph is one **bundle**: a directory holding the graph, the use case it
answers, its golden cases, and the recordings of real models running it. Adding a
graph touches no file any other graph shares, which is what makes parallel
authoring a merge rather than a rebase queue.

Path derivation is concentrated here — `graph_dir`, `cases_path`, `live_dir` and
the matching entry properties are the only code that knows where a bundle keeps
anything. Cases and recordings used to live under `evals/<name>/`; these functions
still resolve that layout, and concentrating them is what let the move land
without every caller moving with it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

def _resolve_root() -> Path:
    """Locate the registry payload.

    An installed wheel carries the registry under ``agenticgraphs/data/`` (see the
    force-include block in pyproject.toml); a git checkout keeps it at the repo root
    so the graphs stay browsable on GitHub and the CARD.md relative links resolve.
    Prefer the packaged copy, fall back to the checkout layout.
    """
    packaged = Path(__file__).resolve().parent / "data"
    if (packaged / "graphs").is_dir():
        return packaged
    return Path(__file__).resolve().parents[2]


ROOT = _resolve_root()
SPEC_DIR = ROOT / "spec"

#: The spec revision every registry graph is written against. One source of truth,
#: so a migration cannot leave stragglers and a test cannot freeze the number.
#:
#: NOTE `agr/v1.6` is deliberately skipped by the registry. It is not a dead number:
#: `_lint_provenance` arms a hard provenance error for graphs declaring exactly
#: v1.6, as a staged opt-in that authors take one graph at a time. Migrating the
#: registry onto v1.6 wholesale would arm that escalation for 83 graphs that were
#: never reviewed for it — `clinical-protocol-lifecycle` asserts `registry_id`, a
#: ground-truth field no binding here can obtain, so it would fail on a rule about
#: provenance while the actual change was about goals.
SPEC_VERSION = "agr/v1.7"


def load_schema(kind: str) -> dict:
    return json.loads((SPEC_DIR / f"agr-{kind}.schema.json").read_text())


def iter_graphs(root: Path = ROOT) -> list[Path]:
    return sorted((root / "graphs").glob("*/*/graph.yaml"))


def iter_yaml(dirname: str, root: Path = ROOT) -> list[Path]:
    return sorted((root / dirname).glob("*.yaml"))


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


# ----------------------------------------------------------------- bundle paths
# One graph is one directory. Everything authored about it -- the graph, the use
# case it answers, its golden cases, and the recordings of real models running it
# -- lives together, so adding a graph touches no file any other graph shares.
#
# `cases.yaml` and `live/` used to live under `evals/<name>/`. These three
# functions are the whole of that knowledge: they prefer the bundle and fall back
# to the old tree, so the move lands without every caller moving in the same
# commit. The fallback goes away one release after the last one does.

def graph_dir(name: str, root: Path = ROOT) -> Path | None:
    """The bundle directory for `name`, or None if no such graph."""
    for g in iter_graphs(root):
        if g.parent.name == name:
            return g.parent
    return None


def cases_path(name: str, root: Path = ROOT) -> Path:
    """Golden cases for `name` — bundle first, legacy `evals/` second.

    Returns the bundle path when neither exists: a file that has yet to be written
    belongs in the new layout, so `agr new` scaffolds forward, not backward.
    """
    bundle = graph_dir(name, root)
    if bundle is not None and (bundle / "cases.yaml").exists():
        return bundle / "cases.yaml"
    legacy = root / "evals" / name / "cases.yaml"
    if legacy.exists():
        return legacy
    return (bundle / "cases.yaml") if bundle is not None else legacy


def live_dir(name: str, root: Path = ROOT) -> Path:
    """Recorded real-model runs for `name` — bundle first, legacy second."""
    bundle = graph_dir(name, root)
    if bundle is not None and (bundle / "live").is_dir():
        return bundle / "live"
    legacy = root / "evals" / name / "live"
    if legacy.is_dir():
        return legacy
    return (bundle / "live") if bundle is not None else legacy


# --------------------------------------------------------------- identity hashes

def sha(obj) -> str:
    """A short, stable content hash. Canonicalised, so key order cannot move it."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]


def shape(doc: dict) -> dict:
    """The projection of a graph that a *recording* is sensitive to.

    Node ids key `node_outputs`; declared `outputs` are shape-checked against the
    reply; edges and termination decide the route; `verification` decides the
    verdict; `goal` decides whether the graph runs at all. A reworded description
    or a renamed speciality changes none of that, and must not invalidate evidence.

    One definition, because A4 measured what happens without one: 71 of 560
    recordings replay against a shape that has since moved, and nothing noticed.
    """
    return {
        "nodes": [{k: n.get(k) for k in
                   ("id", "kind", "outputs", "inputs", "ref", "join", "fan_out",
                    "aggregate", "search", "approval", "on_error")}
                  for n in doc.get("nodes", [])],
        "edges": [{k: e.get(k) for k in ("from", "to", "when", "kind")}
                  for e in doc.get("edges", [])],
        "termination": doc.get("termination"),
        "verification": doc.get("verification"),
        "goal": doc.get("goal"),
        "state": doc.get("state"),
    }


# ------------------------------------------------------------------- evidence

#: Ordered weakest-first. `partial` is the residue: every model scores the same
#: non-zero, non-perfect rate, which no marker in the scoreboard covers today.
EVIDENCE_TIERS = ("none", "unsatisfiable", "flaky", "models-disagree",
                  "partial", "satisfied-all")


@dataclass(frozen=True)
class Evidence:
    """What a graph's recorded real-model runs are actually worth.

    The tier vocabulary is the one `gen_scoreboard.py` already renders (🚫 🎲 ⚠️ ✅),
    lifted here so it has a single definition instead of being re-derived per
    consumer. It is deliberately *unchanged* by this milestone: A2 layers an
    `unproven` grade on top for cells with one sample, and `min_samples` is
    exposed here so it can, but adding it now would silently move published
    counts while the change was supposed to be a refactor.
    """

    tier: str = "none"
    models: tuple[str, ...] = ()
    per_model_pass_rate: dict = field(default_factory=dict)
    samples_per_model: dict = field(default_factory=dict)
    recorded: str = ""
    age_days: int | None = None
    pass_rate: float | None = None
    depth: str = "none"

    @property
    def min_samples(self) -> int:
        """Samples in the thinnest model cell. 1 means 'passed once', not 'passes'."""
        return min(self.samples_per_model.values(), default=0)

    @property
    def stale_risk(self) -> bool:
        """No recording carries the shape it was made against — see A4."""
        return bool(self.models)

    @classmethod
    def from_profile(cls, profile: dict) -> Evidence:
        block = profile.get("measured_live") or {}
        if not block:
            measured = profile.get("measured") or {}
            return cls(depth=measured.get("verification_depth", "none"))
        per_model = block.get("per_model_pass_rate", {})
        if block.get("fails_every_model"):
            tier = "unsatisfiable"
        elif block.get("flaky_models"):
            tier = "flaky"
        elif block.get("models_disagree"):
            tier = "models-disagree"
        elif block.get("pass_rate") == 1.0:
            tier = "satisfied-all"
        else:
            tier = "partial"
        return cls(
            tier=tier,
            models=tuple(block.get("models", ())),
            per_model_pass_rate=dict(per_model),
            samples_per_model=dict(block.get("samples_per_model", {})),
            recorded=block.get("recorded", ""),
            age_days=block.get("age_days"),
            pass_rate=block.get("pass_rate"),
            depth=block.get("verification_depth", "none"),
        )


# --------------------------------------------------------------------- entries

@dataclass(frozen=True)
class RegistryEntry:
    """One graph, joined across every file that says something about it.

    Built by `Registry.load()`; consumers read this instead of re-globbing. The
    `doc` is the parsed graph.yaml — the source of truth — and everything else on
    the entry is derived from it or from a sibling file.
    """

    name: str
    category: str
    path: Path
    doc: dict
    root: Path = ROOT
    entry: dict = field(default_factory=dict)      # the use-case catalog row
    profile: dict = field(default_factory=dict)    # parsed profile.json, {} if absent
    evidence: Evidence = field(default_factory=Evidence)
    #: Ability name -> declared risk, built once per Registry and shared by every
    #: entry. Left None when an entry is constructed standalone.
    ability_risk: dict | None = None

    # -- identity ---------------------------------------------------------
    @property
    def sha(self) -> str:
        """Content hash of the whole graph document."""
        return sha(self.doc)

    @property
    def shape_sha(self) -> str:
        """Content hash of the parts a recording depends on. The A4 marker."""
        return sha(shape(self.doc))

    @property
    def api_version(self) -> str:
        return self.doc.get("apiVersion", "")

    @property
    def motif(self) -> str:
        """The catalog's pattern for this graph — '' when it has no catalog row."""
        return self.entry.get("pattern", "")

    @property
    def description(self) -> str:
        return self.doc.get("description", "")

    # -- contract ---------------------------------------------------------
    @property
    def contract(self) -> str:
        return (self.doc.get("termination") or {}).get("contract", "")

    @property
    def asserts(self) -> tuple[str, ...]:
        return tuple(v["assert"] for v in self.doc.get("verification") or []
                     if "assert" in v)

    @property
    def goal_required(self) -> bool:
        return bool((self.doc.get("goal") or {}).get("required"))

    @property
    def goal_description(self) -> str:
        return (self.doc.get("goal") or {}).get("description", "")

    # -- structure --------------------------------------------------------
    @property
    def structural(self) -> dict:
        # Local import: `inspect` reads the registry, so importing it at module
        # scope would close a cycle. Same shim `harness._asserted_keys` uses.
        from .inspect import structural_profile

        return structural_profile(self.doc, self.root,
                                  ability_risk=self.ability_risk)["structural"]

    @property
    def risk_surface(self) -> str:
        return self.structural["risk_surface"]

    # -- provenance -------------------------------------------------------
    @property
    def mutations(self) -> list[dict]:
        p = self.lineage_path
        return (load(p) or {}).get("mutations", []) if p.exists() else []

    # -- paths ------------------------------------------------------------
    # Bundle first, legacy `evals/` second — see the module-level helpers. The
    # entry already knows its own directory, so it does not re-scan to find it.
    @property
    def cases_path(self) -> Path:
        bundle = self.path.parent / "cases.yaml"
        legacy = self.root / "evals" / self.name / "cases.yaml"
        return bundle if bundle.exists() or not legacy.exists() else legacy

    @property
    def live_dir(self) -> Path:
        bundle = self.path.parent / "live"
        legacy = self.root / "evals" / self.name / "live"
        return bundle if bundle.is_dir() or not legacy.is_dir() else legacy

    @property
    def profile_path(self) -> Path:
        return self.path.parent / "profile.json"

    @property
    def card_path(self) -> Path:
        return self.path.parent / "CARD.md"

    @property
    def lineage_path(self) -> Path:
        return self.path.parent / "lineage.yaml"

    @property
    def has_cases(self) -> bool:
        return self.cases_path.exists()

    def cases(self) -> list[dict]:
        if not self.has_cases:
            return []
        return (load(self.cases_path) or {}).get("cases", [])

    def recordings(self, case_id: str = "") -> list[Path]:
        """Checked-in real-model runs, all of them or just one case's."""
        if not self.live_dir.is_dir():
            return []
        return sorted(self.live_dir.glob(f"{case_id or ''}*.json"))


class Registry:
    """Every graph, joined once.

    `Registry.load()` parses 83 graphs and their profiles in well under a tenth of
    a second, so this is not a cache — it is one definition of the join, held in
    one place, which is the thing that was missing.
    """

    def __init__(self, entries: list[RegistryEntry], root: Path = ROOT):
        self._entries = tuple(entries)
        self._by_name = {e.name: e for e in self._entries}
        self.root = root

    @classmethod
    def load(cls, root: Path = ROOT) -> Registry:
        # The use case a graph answers lives in its bundle. `usecases/catalog.yaml`
        # is a projection of those files (plus the backlog) and is read only as a
        # fallback, for a bundle that has no `usecase.yaml` yet.
        catalog = {}
        cat_file = root / "usecases" / "catalog.yaml"
        if cat_file.exists():
            for row in (load(cat_file) or {}).get("entries", []):
                catalog[row.get("name")] = row

        # Built once and shared: profiling all 83 graphs re-read every ability
        # file twice per graph before this.
        from .inspect import ability_risks

        risks = ability_risks(root)

        entries = []
        for path in iter_graphs(root):
            doc = load(path)
            profile_path = path.parent / "profile.json"
            profile = {}
            if profile_path.exists():
                try:
                    profile = json.loads(profile_path.read_text())
                except json.JSONDecodeError:
                    # A malformed profile is a missing measurement, not a crash:
                    # `agr list` must keep working on a half-written tree.
                    profile = {}
            uc_file = path.parent / "usecase.yaml"
            if uc_file.exists():
                uc = load(uc_file) or {}
                # `name` and `domain` are read off the graph rather than stored
                # twice, so a bundle cannot disagree with itself about what it is.
                use_case = {"id": uc.get("id", ""), "name": doc["name"],
                            "domain": doc["category"], "pattern": uc.get("pattern", ""),
                            "summary": uc.get("summary", ""),
                            "verification": uc.get("verification", "")}
            else:
                use_case = catalog.get(doc["name"], {})
            entries.append(RegistryEntry(
                name=doc["name"], category=doc["category"], path=path, doc=doc,
                root=root, entry=use_case, profile=profile,
                evidence=Evidence.from_profile(profile), ability_risk=risks,
            ))
        return cls(entries, root=root)

    def get(self, name: str) -> RegistryEntry | None:
        return self._by_name.get(name)

    def search(self, term: str) -> list[RegistryEntry]:
        """Substring match over name, description and category.

        Kept exactly as narrow as the CLI and MCP surfaces are today — A3 adds the
        facets. Changing what `search` means and where it lives in one step would
        make a refactor indistinguishable from a feature.
        """
        t = term.lower()
        return [e for e in self._entries
                if t in (e.name + " " + e.description + " " + e.category).lower()]

    def uncovered(self) -> list[dict]:
        """Use cases with no graph — the backlog M12 works through.

        Read from `usecases/backlog/`, one file each, so claiming one is a
        `git mv` into a bundle rather than an edit to a list everybody shares.
        Falls back to the projected catalog for a tree without the backlog dir.
        """
        backlog = self.root / "usecases" / "backlog"
        if backlog.is_dir():
            return [load(p) for p in sorted(backlog.glob("*.yaml"))]
        cat_file = self.root / "usecases" / "catalog.yaml"
        if not cat_file.exists():
            return []
        rows = (load(cat_file) or {}).get("entries", [])
        return [r for r in rows if r.get("name") not in self._by_name]

    def __iter__(self):
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
