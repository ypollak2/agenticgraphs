"""`verification[].command` is the only depth grade settled by an exit code.

Everything else in a contract is a model's account of itself. That makes this the
one field where a defect is not a weaker check but a fake one, so it gets tested
for the two ways it can lie: running something other than what was asked, and
being prose that never runs at all.
"""
from __future__ import annotations

import pytest
import yaml

from agenticgraphs.harness import MockRunner, RunReport, resolve_command, run_graph
from agenticgraphs.registry import iter_graphs, load
from agenticgraphs.validate import _lint_commands

# ------------------------------------------------------------------ placeholders

def test_a_placeholder_is_filled_from_the_blackboard():
    assert resolve_command("pytest -q {test_path}", {"test_path": "tests/x.py"}) == \
        "pytest -q tests/x.py"


def test_a_command_with_no_placeholder_is_unchanged():
    assert resolve_command("pytest -q", {"anything": 1}) == "pytest -q"


def test_a_missing_placeholder_refuses_rather_than_running_a_broader_check():
    """`pytest {suite}` with no `suite` would run the WHOLE suite and report a
    pass for a check that never happened. That is worse than not running."""
    with pytest.raises(KeyError, match="suite"):
        resolve_command("pytest -q {suite}", {})


def test_a_missing_placeholder_is_recorded_as_a_failure_not_a_pass(tmp_path):
    doc = yaml.safe_load("""
apiVersion: agr/v1.8
name: cmd-probe
description: a graph used only by unit tests
category: software-engineering
nodes:
- {id: a, speciality: producer, abilities: [generate], outputs: [ok]}
- {id: v, speciality: critic, abilities: [critique], kind: verifier, outputs: [ok],
   criteria: the recorded command actually ran, rather than being reported as run}
edges: [{from: a, to: v}]
termination: {max_steps: 4, contract: the command runs}
verification:
- {describe: runs the caller's suite, command: "pytest -q {suite}"}
""")
    rep = run_graph(doc, MockRunner({"a": {"ok": True}, "v": {"ok": True}}),
                    root=tmp_path, run_commands=True)
    assert rep.command_failures, "a command that could not be built must not pass"
    assert rep.commands_run == 0
    assert not rep.passed


def test_commands_are_skipped_by_default_and_counted(tmp_path):
    """A skipped command is reported, never silently treated as passing."""
    doc = yaml.safe_load("""
apiVersion: agr/v1.8
name: cmd-skip-probe
description: a graph used only by unit tests
category: software-engineering
nodes:
- {id: a, speciality: producer, abilities: [generate], outputs: [ok]}
- {id: v, speciality: critic, abilities: [critique], kind: verifier, outputs: [ok],
   criteria: an unopted-in command is counted as skipped rather than assumed green}
edges: [{from: a, to: v}]
termination: {max_steps: 4, contract: the command runs}
verification:
- {describe: runs a suite, command: "pytest -q"}
""")
    rep = run_graph(doc, MockRunner({"a": {"ok": True}, "v": {"ok": True}}), root=tmp_path)
    assert rep.skipped_commands == 1
    assert rep.commands_run == 0


def test_a_real_command_runs_and_its_exit_code_is_the_fact(tmp_path):
    for cmd, expect_failure in (("true", False), ("false", True)):
        rep = RunReport()
        from agenticgraphs.harness import _run_command
        _run_command(cmd, tmp_path, rep, {})
        assert rep.commands_run == 1
        assert bool(rep.command_failures) is expect_failure


# ------------------------------------------------------------------------- lint

@pytest.mark.parametrize("cmd", [
    "user-supplied verify command must exit 0",   # the one the registry shipped
    "the command should be run by the caller",
    "run whichever suite is appropriate",
])
def test_prose_in_the_command_field_is_refused(cmd):
    assert _lint_commands({"verification": [{"command": cmd}]})


@pytest.mark.parametrize("cmd", [
    "pytest -q", "alembic upgrade head", "npm test", "{verify_command}",
    "dbt build --select {model_name}", "gitleaks detect --no-banner --redact",
    "grep the notes.txt",  # a function word as a real argument, alongside a path
])
def test_real_command_lines_are_accepted(cmd):
    assert _lint_commands({"verification": [{"command": cmd}]}) == []


def test_an_unparseable_command_is_refused():
    assert _lint_commands({"verification": [{"command": 'pytest "unclosed'}]})


# --------------------------------------------------------------------- registry

def test_every_registry_command_is_runnable_and_its_inputs_are_declared():
    """A placeholder no caller is told to supply is a check that cannot run."""
    for gpath in iter_graphs():
        doc = load(gpath)
        declared = set((doc.get("state") or {}).get("inputs") or [])
        for v in doc.get("verification") or []:
            cmd = v.get("command")
            if not cmd:
                continue
            assert _lint_commands({"verification": [v]}) == [], doc["name"]
            import re
            for key in re.findall(r"\{([A-Za-z_][A-Za-z_0-9]*)\}", cmd):
                assert key in declared, (
                    f"{doc['name']}: command needs '{key}' but state.inputs does not "
                    f"declare it, so no caller knows to supply it"
                )


def test_executable_checks_cover_the_graphs_that_can_have_them():
    """The registry shipped exactly one command, and it was prose. This pins that
    the honest set stays covered rather than eroding back to claims."""
    n = sum(1 for gpath in iter_graphs()
            for v in (load(gpath).get("verification") or []) if "command" in v)
    assert n >= 20, f"executable verification commands regressed to {n}"
