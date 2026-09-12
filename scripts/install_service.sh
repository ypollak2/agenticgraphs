#!/usr/bin/env bash
# Install (or uninstall) agenticgraphs' MCP server as an always-on macOS
# LaunchAgent, so the registry's abilities are reachable over HTTP without a
# human keeping a terminal open.
#
# The agent runs: <repo>/.venv/bin/agr mcp --http --port 8765
# bound to 127.0.0.1 only (see src/agenticgraphs/mcp_server.py). It is NOT
# started by this script automatically running anything privileged — it only
# writes the plist and asks launchd to bootstrap it (RunAtLoad + KeepAlive).
#
# A bearer token is generated on first install and exported in the plist, so the
# server refuses any local process that does not present it. Before 2026-09-12
# the plist carried no EnvironmentVariables at all, which cost two things at
# once: loopback was the only access control, and `run_graph(live=True)` — which
# refuses to spend on an endpoint for an unauthenticated caller — was therefore
# permanently unreachable. The guard was off and the feature it guards was off,
# from the same absent variable. Pass --no-token for the old posture.
#
# The token is kept at ~/.config/agenticgraphs/mcp-token (0600) and reused on
# reinstall, so a client configured once keeps working.
#
# Usage:
#   scripts/install_service.sh              # install + load (restarts if running)
#   scripts/install_service.sh --restart    # pick up new code, plist unchanged
#   scripts/install_service.sh --uninstall  # unload + remove
#
# KeepAlive keeps this daemon alive across every merge, and nothing restarts it
# when the checkout moves. The 2026-09-12 audit found one that had been serving a
# 34-day-old revision: six tools shipped five weeks earlier were unreachable, and
# `tools/list` looked perfectly healthy. Run --restart after a merge, and call the
# server's `server_info` tool to confirm the revision it reports is the one you
# expect.
#
# This script must be run manually by a human; it is never invoked by `agr`
# itself or by any headless/autonomous recipe.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: this installer targets macOS launchd only" >&2
  exit 1
fi

LABEL="com.ypollak2.agenticgraphs-mcp"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs"
LOG_PATH="$LOG_DIR/agenticgraphs-mcp.log"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${AGR_MCP_PORT:-8765}"

UNINSTALL=0
RESTART=0
NO_TOKEN=0
for arg in "$@"; do
  case "$arg" in
    --uninstall) UNINSTALL=1 ;;
    --restart) RESTART=1 ;;
    --no-token) NO_TOKEN=1 ;;
    *) echo "error: unknown argument '$arg'" >&2; exit 1 ;;
  esac
done

TOKEN_DIR="$HOME/.config/agenticgraphs"
TOKEN_FILE="$TOKEN_DIR/mcp-token"

# A plist that still shells through `uv run` leaves an orphan on restart. Say so
# rather than reporting a restart that did not replace the running server.
plist_is_direct() {
  [[ -f "$PLIST_PATH" ]] && ! grep -q "<string>run</string>" "$PLIST_PATH"
}

if [[ "$RESTART" -eq 1 ]]; then
  if [[ ! -f "$PLIST_PATH" ]]; then
    echo "error: $LABEL is not installed — run without --restart first" >&2
    exit 1
  fi
  if ! plist_is_direct; then
    echo "error: the installed plist launches the server through 'uv run', which" >&2
    echo "       survives kickstart as an orphan. Reinstall first:" >&2
    echo "         scripts/install_service.sh" >&2
    exit 1
  fi
  echo "restarting $LABEL ..."
  launchctl kickstart -k "gui/$(id -u)/${LABEL}"
  echo "restarted. Confirm what it now serves:"
  echo "  the MCP \`server_info\` tool reports {revision, dirty, spec_version, graphs}"
  exit 0
fi

if [[ "$UNINSTALL" -eq 1 ]]; then
  echo "unloading $LABEL ..."
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "removed $PLIST_PATH"
  exit 0
fi

# launchd must supervise the server itself, not a launcher that spawns it.
# The plist ran `uv run agr mcp`, which forks a child python; `launchctl
# kickstart -k` then killed the `uv` parent and left the child running, orphaned
# to pid 1 and deaf to SIGTERM (uvicorn's graceful shutdown never completed). On
# 2026-09-12 one such orphan was found still alive from 9 Aug, five weeks and one
# merge behind, and a restart looked like it had worked. Exec the venv's `agr`
# directly so there is one process and launchd owns it.
AGR_BIN="${REPO_DIR}/.venv/bin/agr"
if [[ ! -x "$AGR_BIN" ]]; then
  echo "error: $AGR_BIN not found — run 'uv sync --all-extras' in ${REPO_DIR} first" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR"

# Reuse an existing token so a client configured once keeps working across
# reinstalls; mint one on first install.
TOKEN=""
ENV_BLOCK=""
if [[ "$NO_TOKEN" -eq 0 ]]; then
  mkdir -p "$TOKEN_DIR"
  chmod 700 "$TOKEN_DIR"
  if [[ ! -s "$TOKEN_FILE" ]]; then
    openssl rand -hex 32 > "$TOKEN_FILE"
    echo "minted a new bearer token at ${TOKEN_FILE}"
  fi
  chmod 600 "$TOKEN_FILE"
  TOKEN="$(tr -d '\n' < "$TOKEN_FILE")"
  ENV_BLOCK="    <key>EnvironmentVariables</key>
    <dict>
        <key>AGR_MCP_TOKEN</key>
        <string>${TOKEN}</string>
    </dict>"
fi

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${AGR_BIN}</string>
        <string>mcp</string>
        <string>--http</string>
        <string>--port</string>
        <string>${PORT}</string>
    </array>
${ENV_BLOCK}
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_PATH}</string>
    <key>WorkingDirectory</key>
    <string>${REPO_DIR}</string>
</dict>
</plist>
PLIST

# The plist holds the token, so it is not world-readable.
chmod 600 "$PLIST_PATH"
echo "wrote ${PLIST_PATH}"

# Reload cleanly if it's already bootstrapped.
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/${LABEL}"

# Bootstrapping a plist that launchd already holds is a no-op for a running
# process, so kickstart unconditionally: an installer that leaves the old code
# running is exactly the failure this script now documents.
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "installed and bootstrapped ${LABEL} (logs: ${LOG_PATH})"
echo "check with: launchctl print gui/$(id -u)/${LABEL}"
echo "confirm the served revision with the MCP \`server_info\` tool"

if [[ -n "$TOKEN" ]]; then
  cat <<INFO

This server now requires a bearer token. Point an MCP client at it with:

  {"type": "http", "url": "http://127.0.0.1:${PORT}/mcp",
   "headers": {"Authorization": "Bearer \$(cat ${TOKEN_FILE})"}}

A client configured without it gets 401. Re-run with --no-token to go back to
loopback-only access, which also makes run_graph(live=true) permanently refuse.
INFO
fi
