#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AUTO_SYNC_DIR="$PROJECT_ROOT/.remote/auto_sync"
PID_FILE="$AUTO_SYNC_DIR/pid"
STATUS_FILE="$AUTO_SYNC_DIR/status"
LOG_FILE="$AUTO_SYNC_DIR/auto_sync.log"
WATCHER="$SCRIPT_DIR/watch_workspace.sh"

if [[ -f "$PID_FILE" ]]; then
  watcher_pid="$(tr -d '[:space:]' <"$PID_FILE")"
  watcher_command="$(ps -p "$watcher_pid" -o command= 2>/dev/null || true)"
  if [[ "$watcher_pid" =~ ^[0-9]+$ && "$watcher_command" == *"$WATCHER"* ]]; then
    echo "running=true"
    echo "pid=$watcher_pid"
  else
    echo "running=false"
    echo "state=stale_pid_file"
  fi
else
  echo "running=false"
fi

if [[ -f "$STATUS_FILE" ]]; then
  echo "status=$(cat "$STATUS_FILE")"
fi
if [[ -f "$LOG_FILE" ]]; then
  echo "log=$LOG_FILE"
  tail -n 12 "$LOG_FILE"
fi
