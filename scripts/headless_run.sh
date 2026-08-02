#!/usr/bin/env bash
# Non-interactive Claude Code recipe: search the registry for a graph, eval
# it, and write a timestamped Markdown report to reports/ — with no human at
# the keyboard. Intended to be run from cron/launchd (examples below) or
# invoked ad hoc.
#
# This deliberately does NOT pass --dangerously-skip-permissions: the task is
# scoped to a single allowed tool pattern instead, so an unattended run can
# only ever shell out to `uv run agr ...` and nothing else.
#
# Usage:
#   scripts/headless_run.sh [search-term] [graph-name]
#
# Examples:
#   scripts/headless_run.sh                                   # defaults below
#   scripts/headless_run.sh "code review" code-review-pipeline
#   scripts/headless_run.sh "research" cost-routed-research
#
# --- cron example (nightly at 03:00) -----------------------------------
#   0 3 * * * /usr/bin/env bash /path/to/agenticgraphs/scripts/headless_run.sh \
#       "code review" code-review-pipeline >> ~/Library/Logs/agr-headless.log 2>&1
#
# --- launchd example (com.ypollak2.agenticgraphs-headless.plist) -------
#   <key>ProgramArguments</key>
#   <array>
#       <string>/path/to/agenticgraphs/scripts/headless_run.sh</string>
#       <string>code review</string>
#       <string>code-review-pipeline</string>
#   </array>
#   <key>StartCalendarInterval</key>
#   <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>
# -------------------------------------------------------------------------
set -euo pipefail

SEARCH_TERM="${1:-code review}"
GRAPH_NAME="${2:-code-review-pipeline}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORTS_DIR="$REPO_DIR/reports"
mkdir -p "$REPORTS_DIR"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_PATH="$REPORTS_DIR/${GRAPH_NAME}-${TS}.md"

if ! command -v claude >/dev/null 2>&1; then
  echo "error: 'claude' (Claude Code CLI) not found on PATH" >&2
  exit 1
fi

TASK=$(cat <<EOF
Working directory: ${REPO_DIR}. Using only the agenticgraphs 'agr' CLI via
'uv run agr ...', do the following and reply with a single Markdown report
(no preamble, no code fences around the whole report):

1. Run \`uv run agr search "${SEARCH_TERM}"\` and note the matching graphs.
2. Run \`uv run agr show ${GRAPH_NAME}\` to confirm it exists and inspect it.
3. Run \`uv run agr eval ${GRAPH_NAME}\` to execute its golden cases.
4. Write a Markdown report with: a "## Search results" section listing the
   search hits, a "## Eval results" section with the pass rate and measured
   step counts from step 3, and a one-paragraph "## Notes" section flagging
   anything that looks wrong (missing graph, failing cases, etc).

Do not modify any files. Do not run \`agr infuse\` or \`agr optimize --apply\`.
EOF
)

claude -p "$TASK" \
  --allowedTools "Bash(uv run agr *)" \
  > "$REPORT_PATH"

echo "wrote ${REPORT_PATH}"
