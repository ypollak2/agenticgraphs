#!/usr/bin/env bash
# Install (or uninstall) agenticgraphs' MCP server as an always-on macOS
# LaunchAgent, so the registry's abilities are reachable over HTTP without a
# human keeping a terminal open.
#
# The agent runs: uv --directory <repo> run agr mcp --http --port 8765
# bound to 127.0.0.1 only (see src/agenticgraphs/mcp_server.py). It is NOT
# started by this script automatically running anything privileged — it only
# writes the plist and asks launchd to bootstrap it (RunAtLoad + KeepAlive).
#
# Usage:
#   scripts/install_service.sh              # install + load
#   scripts/install_service.sh --uninstall  # unload + remove
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
for arg in "$@"; do
  case "$arg" in
    --uninstall) UNINSTALL=1 ;;
    *) echo "error: unknown argument '$arg'" >&2; exit 1 ;;
  esac
done

if [[ "$UNINSTALL" -eq 1 ]]; then
  echo "unloading $LABEL ..."
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "removed $PLIST_PATH"
  exit 0
fi

UV_BIN="$(command -v uv || true)"
if [[ -z "$UV_BIN" ]]; then
  echo "error: 'uv' not found on PATH — install it first (https://docs.astral.sh/uv/)" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${UV_BIN}</string>
        <string>--directory</string>
        <string>${REPO_DIR}</string>
        <string>run</string>
        <string>agr</string>
        <string>mcp</string>
        <string>--http</string>
        <string>--port</string>
        <string>${PORT}</string>
    </array>
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

echo "wrote ${PLIST_PATH}"

# Reload cleanly if it's already bootstrapped.
launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/${LABEL}"

echo "installed and bootstrapped ${LABEL} (logs: ${LOG_PATH})"
echo "check with: launchctl print gui/$(id -u)/${LABEL}"
