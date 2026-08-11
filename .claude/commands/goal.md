---
description: Run a registry graph against a stated goal, asking for one when the session has none
argument-hint: <goal> [|| <graph-name>]
---

Run an AGR graph against a goal. The goal is the thing this registry spent five
versions not having: every graph used to start with an empty blackboard and invent a
plausible subject, which is how a contract can pass while answering a question nobody
asked. Graphs with `goal.required` now refuse instead.

**Never invent a goal.** If you cannot find one, ask. A fabricated goal produces a run
that looks successful and means nothing — the exact failure this command exists to
prevent.

Steps:

1. Split `$ARGUMENTS` on the first `||` into `<goal>` (left) and an optional explicit
   `<graph-name>` (right), trimming whitespace.

2. **Establish the goal.** In order:
   - the `<goal>` text, if given;
   - otherwise a specific request stated earlier in this session that the chosen graph
     plainly covers — quote it back to the user and confirm before using it;
   - otherwise **stop and ask the user what the goal is.** Do not proceed on a guess,
     do not derive one from the repo state, and do not use the graph's own
     `goal.description` as the goal — that text says what to bring, it is not itself an
     answer.

3. **Choose the graph.** If `<graph-name>` was given, use it. Otherwise call the
   `search_graphs` MCP tool (or `uv run agr search <term>`) with terms from the goal.
   Each result carries `goal_required` and `goal_description`. If several fit, list the
   candidates with their contracts and ask which one — do not pick silently.

4. **Check what the graph demands.** Read its `goal` block and `state.inputs`
   (`uv run agr show <name>`). If `goal.required` is set and step 2 did not produce a
   goal, ask — quoting the graph's `goal.description` verbatim, since that text exists
   to tell the caller what to bring. If the graph declares other `state.inputs` beyond
   `goal`, say which ones the run will not have.

5. **Run it:** `uv run --all-extras agr goal <name> "<goal>"`. Add `--live` only if the
   user asked for a real model, and `--run-commands` only if they accepted that it
   executes code on this machine.

6. **Report what the pass is worth, not just that it passed.** Give the verdict, the
   contract it was judged against, and the `verification_depth` from the output. A pass
   at `assert-fixture` proves the topology routed values; only `assert-grounded` means a
   claim traced to a real tool call. If `goal_missing` is set, the graph refused — say
   what it wanted rather than reporting a failure.

Never report a result you did not obtain from the command's actual output.
