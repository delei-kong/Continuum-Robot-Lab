#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AUTO_SYNC_DIR="$PROJECT_ROOT/.remote/auto_sync"
PID_FILE="$AUTO_SYNC_DIR/pid"
WATCHER="$SCRIPT_DIR/watch_workspace.sh"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Auto-sync watcher is not running."
  exit 0
fi

watcher_pid="$(tr -d '[:space:]' <"$PID_FILE")"
watcher_command="$(ps -p "$watcher_pid" -o command= 2>/dev/null || true)"
if [[ ! "$watcher_pid" =~ ^[0-9]+$ || "$watcher_command" != *"$WATCHER"* ]]; then
  echo "Removing stale auto-sync PID state; no matching watcher process exists."
  rm -f "$PID_FILE"
  rmdir "$AUTO_SYNC_DIR/daemon.lock" 2>/dev/null || true
  exit 0
fi

kill "$watcher_pid"
for _ in 1 2 3 4 5; do
  if ! kill -0 "$watcher_pid" 2>/dev/null; then
    echo "Stopped auto-sync watcher PID $watcher_pid."
    exit 0
  fi
  sleep 1
done

echo "Watcher PID $watcher_pid did not stop within five seconds." >&2
exit 1
