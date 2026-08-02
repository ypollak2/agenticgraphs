"""Autonomy gate: opt-in, safe-by-default unattended writes.

Default posture is the same as before this module existed: nothing persists
without a human at a checkout. Setting `AGR_AUTONOMOUS=1` (or passing
`autonomous=True` through the CLI/MCP layer) opts a specific run into writing
back to the registry — but only after the same schema + MAST-lint gate every
other mutation goes through, and only onto a dedicated `auto/mutations`
branch (never `main`, never pushed).

Abilities whose `risk` is `execute` are further capped: autonomous persist of
an `execute`-risk ability is refused unless `AGR_AUTONOMOUS_ALLOW_EXECUTE=1`
is *also* set. See docs/autonomy.md for the full rationale.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .registry import ROOT

AUTO_BRANCH = "auto/mutations"

HUMAN_OWNED_CHECKOUT_MSG = (
    "autonomous persist refused: AGR_AUTONOMOUS is not set. "
    "Writing to the registry is a human-owned-checkout operation by default — "
    "set AGR_AUTONOMOUS=1 (or pass --autonomous / persist through an autonomous "
    "run) to opt this run into unattended writes. See docs/autonomy.md."
)

EXECUTE_RISK_MSG = (
    "autonomous persist refused: ability risk surface is 'execute'. "
    "Execute-risk abilities are capped even under AGR_AUTONOMOUS — set "
    "AGR_AUTONOMOUS_ALLOW_EXECUTE=1 to explicitly allow it. See docs/autonomy.md."
)


class AutonomyError(RuntimeError):
    """Raised when an autonomous write is refused by policy (the gate is closed)."""


class _GitCmdError(RuntimeError):
    """Internal: a git plumbing subprocess exited non-zero. Not a policy signal."""


def is_autonomous() -> bool:
    """True if this run has opted into unattended persistence."""
    return os.environ.get("AGR_AUTONOMOUS") == "1"


def execute_allowed() -> bool:
    """True if this run additionally allows persisting execute-risk abilities."""
    return os.environ.get("AGR_AUTONOMOUS_ALLOW_EXECUTE") == "1"


def require_autonomous() -> None:
    """Raise AutonomyError unless AGR_AUTONOMOUS=1 is set for this process."""
    if not is_autonomous():
        raise AutonomyError(HUMAN_OWNED_CHECKOUT_MSG)


def require_execute_allowed(risk: str) -> None:
    """Raise AutonomyError if `risk` is 'execute' and the execute-override isn't set."""
    if risk == "execute" and not execute_allowed():
        raise AutonomyError(EXECUTE_RISK_MSG)


def _git(root: Path, *args: str, env: dict | None = None) -> str:
    res = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, env=env,
    )
    if res.returncode != 0:
        raise _GitCmdError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
    return res.stdout.strip()


def _git_config(root: Path, key: str, default: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(root), "config", key],
        capture_output=True, text=True,
    )
    return res.stdout.strip() or default


def commit_autonomous_mutation(root: Path, paths: list[Path], message: str) -> str:
    """Commit `paths` (already written on disk) onto `AUTO_BRANCH`, never touching
    `main`, the caller's real index, or the currently checked-out branch.

    Uses git plumbing with a scratch index so this can run against a live,
    human-owned checkout without disturbing anything the human has staged or
    checked out. Returns the new commit sha.
    """
    root = Path(root)
    scratch_index = root / ".git" / f"agr-autonomy-index-{os.getpid()}"
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(scratch_index)
    author_name = _git_config(root, "user.name", "agenticgraphs-autonomy")
    author_email = _git_config(root, "user.email", "autonomy@agenticgraphs.local")
    env["GIT_AUTHOR_NAME"] = author_name
    env["GIT_AUTHOR_EMAIL"] = author_email
    env["GIT_COMMITTER_NAME"] = author_name
    env["GIT_COMMITTER_EMAIL"] = author_email
    try:
        try:
            parent = _git(root, "rev-parse", "--verify", f"refs/heads/{AUTO_BRANCH}")
        except _GitCmdError:
            parent = _git(root, "rev-parse", "--verify", "HEAD")
        _git(root, "read-tree", parent, env=env)
        rel_paths = [str(Path(p).resolve().relative_to(root)) for p in paths]
        _git(root, "add", "--", *rel_paths, env=env)
        tree = _git(root, "write-tree", env=env)
        commit = _git(root, "commit-tree", tree, "-p", parent, "-m", message, env=env)
        _git(root, "update-ref", f"refs/heads/{AUTO_BRANCH}", commit)
        return commit
    finally:
        scratch_index.unlink(missing_ok=True)
