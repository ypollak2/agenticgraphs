"""Tests for the autonomy gate: opt-in, safe-by-default unattended writes.

Three layers, matching the task's quality bar:
  1. The gate primitives (`autonomy.require_autonomous` / `require_execute_allowed`)
     in isolation — no filesystem or git side effects.
  2. `mutate.infuse_autonomous` wiring: refusals never touch disk or git; the one
     success-path test that does write runs against a throwaway git clone, never
     the real development repo.
  3. `commit_autonomous_mutation`'s branch-commit logic, against a tmp git repo
     fixture (per the task's explicit instruction), and a thin MCP-layer wiring
     check plus `--http` CLI argument parsing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agenticgraphs.autonomy import (
    AutonomyError,
    commit_autonomous_mutation,
    execute_allowed,
    is_autonomous,
    require_autonomous,
    require_execute_allowed,
)
from agenticgraphs.mutate import infuse_autonomous
from agenticgraphs.registry import ROOT

# ---------------------------------------------------------------------------
# 1. Gate primitives
# ---------------------------------------------------------------------------

def test_require_autonomous_refused_without_env(monkeypatch):
    monkeypatch.delenv("AGR_AUTONOMOUS", raising=False)
    assert is_autonomous() is False
    with pytest.raises(AutonomyError, match="AGR_AUTONOMOUS is not set"):
        require_autonomous()


def test_require_autonomous_allowed_with_env(monkeypatch):
    monkeypatch.setenv("AGR_AUTONOMOUS", "1")
    assert is_autonomous() is True
    require_autonomous()  # must not raise


def test_require_execute_allowed_refused_without_env(monkeypatch):
    monkeypatch.delenv("AGR_AUTONOMOUS_ALLOW_EXECUTE", raising=False)
    assert execute_allowed() is False
    with pytest.raises(AutonomyError, match="risk surface is 'execute'"):
        require_execute_allowed("execute")


def test_require_execute_allowed_with_env(monkeypatch):
    monkeypatch.setenv("AGR_AUTONOMOUS_ALLOW_EXECUTE", "1")
    require_execute_allowed("execute")  # must not raise


@pytest.mark.parametrize("risk", ["read", "write"])
def test_require_execute_allowed_never_blocks_non_execute_risk(monkeypatch, risk):
    monkeypatch.delenv("AGR_AUTONOMOUS_ALLOW_EXECUTE", raising=False)
    require_execute_allowed(risk)  # must not raise regardless of env


# ---------------------------------------------------------------------------
# 2. infuse_autonomous wiring — refusals touch nothing; success path is isolated
# ---------------------------------------------------------------------------

def test_infuse_autonomous_refused_without_env(monkeypatch):
    monkeypatch.delenv("AGR_AUTONOMOUS", raising=False)
    with pytest.raises(AutonomyError, match="AGR_AUTONOMOUS is not set"):
        infuse_autonomous("code-review-pipeline", "style-review", "edit_files")


def test_infuse_autonomous_refuses_execute_risk_ability(monkeypatch):
    monkeypatch.setenv("AGR_AUTONOMOUS", "1")
    monkeypatch.delenv("AGR_AUTONOMOUS_ALLOW_EXECUTE", raising=False)
    with pytest.raises(AutonomyError, match="risk surface is 'execute'"):
        infuse_autonomous("code-review-pipeline", "triage", "run_command")


@pytest.fixture
def repo_clone(tmp_path):
    """A throwaway local clone of the real repo, so the one test that exercises
    a real autonomous write + commit never touches the development repo's git
    history (no stray `auto/mutations` branch left behind).
    """
    dst = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(dst)], check=True)
    # Pin the clone to a branch of our own. Cloning a source repo that is itself in
    # detached HEAD — which is exactly what a tag build checks out in CI — otherwise
    # leaves the clone with no branch, and `symbolic-ref HEAD` below exits 128.
    subprocess.run(["git", "-C", str(dst), "checkout", "-q", "-B", "agr-test-base"], check=True)
    subprocess.run(["git", "-C", str(dst), "config", "user.name", "Autonomy Test"], check=True)
    subprocess.run(["git", "-C", str(dst), "config", "user.email", "autonomy-test@example.com"], check=True)
    return dst


def test_infuse_autonomous_persists_and_commits_on_auto_mutations_branch(monkeypatch, repo_clone):
    monkeypatch.setenv("AGR_AUTONOMOUS", "1")
    checked_out_before = subprocess.run(
        ["git", "-C", str(repo_clone), "symbolic-ref", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    # web_search is bound (read risk). An unbound world-effect like edit_files is
    # now refused by _lint_unbound (R3-04) — see the test below.
    result = infuse_autonomous("code-review-pipeline", "style-review", "web_search", root=repo_clone)

    assert result["changed"] is True
    assert result["branch"] == "auto/mutations"
    commit = result["commit"]
    assert commit

    # Landed on auto/mutations, not on the branch the clone had checked out.
    checked_out_after = subprocess.run(
        ["git", "-C", str(repo_clone), "symbolic-ref", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert checked_out_after == checked_out_before

    branch_tip = subprocess.run(
        ["git", "-C", str(repo_clone), "rev-parse", "auto/mutations"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert branch_tip == commit

    committed_graph = subprocess.run(
        ["git", "-C", str(repo_clone), "show",
         f"{commit}:graphs/software-engineering/code-review-pipeline/graph.yaml"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "edit_files" in committed_graph

    # The mutation was written to the working tree too (that's what got staged).
    on_disk = (repo_clone / "graphs/software-engineering/code-review-pipeline/graph.yaml").read_text()
    assert "edit_files" in on_disk


# ---------------------------------------------------------------------------
# 3. commit_autonomous_mutation — branch-commit logic (tmp git repo fixture)
# ---------------------------------------------------------------------------

def _init_repo(path: Path, identity: bool = True) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    if identity:
        subprocess.run(["git", "-C", str(path), "config", "user.name", "Test User"], check=True)
        subprocess.run(["git", "-C", str(path), "config", "user.email", "test@example.com"], check=True)
    (path / "tracked.txt").write_text("hello\n")
    subprocess.run(["git", "-C", str(path), "add", "tracked.txt"], check=True)
    commit_cmd = ["git", "-C", str(path)]
    if not identity:
        # Bootstrap the initial commit without leaving any identity in repo config,
        # so commit_autonomous_mutation's fallback default is genuinely exercised.
        commit_cmd += ["-c", "user.name=Init Bootstrap", "-c", "user.email=bootstrap@example.com"]
    commit_cmd += ["commit", "-q", "-m", "init"]
    subprocess.run(commit_cmd, check=True)


def _rev(repo: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_commit_autonomous_mutation_creates_branch_without_touching_main(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    main_before = _rev(repo, "main")
    target = repo / "tracked.txt"
    target.write_text("mutated\n")

    commit = commit_autonomous_mutation(repo, [target], "auto: test mutation one")

    assert _rev(repo, "main") == main_before  # main is never touched
    assert _rev(repo, "auto/mutations") == commit

    checked_out = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert checked_out == "main"  # the checkout is never switched

    # The human's working tree / index on `main` still shows the edit as an
    # ordinary uncommitted change — proving the commit landed via a scratch
    # index, not the repo's real index.
    status = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "tracked.txt" in status

    show = subprocess.run(
        ["git", "-C", str(repo), "show", f"{commit}:tracked.txt"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert show == "mutated\n"

    author = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%an <%ae>", commit],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert author == "Test User <test@example.com>"


def test_commit_autonomous_mutation_extends_existing_branch(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    target = repo / "tracked.txt"

    target.write_text("first change\n")
    first = commit_autonomous_mutation(repo, [target], "auto: first")

    target.write_text("second change\n")
    second = commit_autonomous_mutation(repo, [target], "auto: second")

    parent = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%P", second],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert parent == first  # extends the branch tip, not re-forked from main each time
    assert _rev(repo, "auto/mutations") == second

    show = subprocess.run(
        ["git", "-C", str(repo), "show", f"{second}:tracked.txt"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert show == "second change\n"


def test_commit_autonomous_mutation_falls_back_to_generic_identity(tmp_path, monkeypatch):
    # Isolate from any real/global git identity so the fallback path is genuinely exercised.
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(fake_home / "no-such-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(fake_home / "no-such-gitconfig"))
    repo = tmp_path / "repo"
    _init_repo(repo, identity=False)
    target = repo / "tracked.txt"
    target.write_text("mutated\n")

    commit = commit_autonomous_mutation(repo, [target], "auto: fallback identity")

    author = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%an <%ae>", commit],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert author == "agenticgraphs-autonomy <autonomy@agenticgraphs.local>"


# ---------------------------------------------------------------------------
# MCP-layer wiring: infuse_ability(persist=true) refuses the same way
# ---------------------------------------------------------------------------

def test_mcp_infuse_ability_persist_refused_without_env(monkeypatch):
    pytest.importorskip("mcp")
    import asyncio

    from agenticgraphs.mcp_server import create_server

    monkeypatch.delenv("AGR_AUTONOMOUS", raising=False)
    server = create_server()
    with pytest.raises(Exception, match="AGR_AUTONOMOUS is not set"):
        asyncio.run(server.call_tool(
            "infuse_ability",
            {"name": "code-review-pipeline", "node_id": "style-review",
             "ability": "edit_files", "persist": True},
        ))


# ---------------------------------------------------------------------------
# --http CLI argument parsing
# ---------------------------------------------------------------------------

def test_cli_mcp_defaults_to_stdio(monkeypatch):
    from agenticgraphs.cli import main

    calls = []
    monkeypatch.setattr("agenticgraphs.mcp_server.main", lambda **kw: calls.append(kw))
    assert main(["mcp"]) == 0
    assert calls == [{"http": False, "port": 8765}]


def test_cli_mcp_http_flag_with_default_port(monkeypatch):
    from agenticgraphs.cli import main

    calls = []
    monkeypatch.setattr("agenticgraphs.mcp_server.main", lambda **kw: calls.append(kw))
    assert main(["mcp", "--http"]) == 0
    assert calls == [{"http": True, "port": 8765}]


def test_cli_mcp_http_flag_with_custom_port(monkeypatch):
    from agenticgraphs.cli import main

    calls = []
    monkeypatch.setattr("agenticgraphs.mcp_server.main", lambda **kw: calls.append(kw))
    assert main(["mcp", "--http", "--port", "9999"]) == 0
    assert calls == [{"http": True, "port": 9999}]


def test_infuse_autonomous_refuses_an_unbound_world_effect(monkeypatch, repo_clone):
    """An unattended write must not add an effect the runtime cannot execute:
    the node would narrate `edit_files` and nothing would edit (R3-04)."""
    import pytest

    monkeypatch.setenv("AGR_AUTONOMOUS", "1")
    with pytest.raises(SystemExit, match="no binding"):
        infuse_autonomous("code-review-pipeline", "style-review", "edit_files", root=repo_clone)
