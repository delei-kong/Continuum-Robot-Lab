#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AUTO_SYNC_DIR="$PROJECT_ROOT/.remote/auto_sync"
PID_FILE="$AUTO_SYNC_DIR/pid"
START_LOCK="$AUTO_SYNC_DIR/start.lock"
WATCHER="$SCRIPT_DIR/watch_workspace.sh"
QUIET=false

if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=true
fi

mkdir -p "$AUTO_SYNC_DIR"
if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(tr -d '[:space:]' <"$PID_FILE")"
  if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
    existing_command="$(ps -p "$existing_pid" -o command= 2>/dev/null || true)"
    if [[ "$existing_command" == *"$WATCHER"* ]]; then
      $QUIET || echo "Auto-sync watcher is already running with PID $existing_pid."
      exit 0
    fi
  fi
fi

if ! mkdir "$START_LOCK" 2>/dev/null; then
  $QUIET || echo "Another shell is starting the auto-sync watcher."
  exit 0
fi
cleanup_start_lock() {
  rmdir "$START_LOCK" 2>/dev/null || true
}
trap cleanup_start_lock EXIT INT TERM

rm -f "$PID_FILE"
rmdir "$AUTO_SYNC_DIR/daemon.lock" 2>/dev/null || true
nohup "$WATCHER" >>"$AUTO_SYNC_DIR/auto_sync.log" 2>&1 &
watcher_pid=$!
sleep 1

if ! kill -0 "$watcher_pid" 2>/dev/null; then
  echo "Auto-sync watcher failed to start. See $AUTO_SYNC_DIR/auto_sync.log" >&2
  exit 1
fi

$QUIET || echo "Started auto-sync watcher with PID $watcher_pid."
