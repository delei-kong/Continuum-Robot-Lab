#!/usr/bin/env bash

# Manage the one guarded workspace-sync watcher.  This script deliberately
# keeps start/status/stop as subcommands so a user cannot accidentally launch
# three differently implemented watcher lifecycles.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AUTO_SYNC_DIR="$PROJECT_ROOT/.remote/auto_sync"
PID_FILE="$AUTO_SYNC_DIR/pid"
DAEMON_LOCK="$AUTO_SYNC_DIR/daemon.lock"
START_LOCK="$AUTO_SYNC_DIR/start.lock"
STATUS_FILE="$AUTO_SYNC_DIR/status"
LOG_FILE="$AUTO_SYNC_DIR/auto_sync.log"
ERROR_LOG_FILE="$AUTO_SYNC_DIR/auto_sync.error.log"
WATCHER="$SCRIPT_DIR/watch_workspace.sh"

usage() {
  cat <<EOF
Usage: $0 <start|status|stop> [--quiet]

Commands:
  start [--quiet]  start one watcher unless a matching watcher is already running
  status           report watcher PID, latest state, and recent logs
  stop             request a graceful stop and wait for local locks to be released
EOF
}

process_is_watcher() {
  local candidate_pid="${1:-}"
  local candidate_command
  [[ "$candidate_pid" =~ ^[0-9]+$ ]] || return 1
  candidate_command="$(ps -p "$candidate_pid" -o command= 2>/dev/null || true)"
  [[ "$candidate_command" == *"$WATCHER"* ]]
}

discover_watcher_pid() {
  local candidate_pid candidate_command
  while read -r candidate_pid candidate_command; do
    if [[ "$candidate_command" == *"$WATCHER"* ]]; then
      printf '%s\n' "$candidate_pid"
      return 0
    fi
  done < <(ps -ax -o pid= -o command=)
  return 1
}

recorded_watcher_pid() {
  local candidate_pid
  [[ -f "$PID_FILE" ]] || return 1
  candidate_pid="$(tr -d '[:space:]' <"$PID_FILE")"
  if process_is_watcher "$candidate_pid"; then
    printf '%s\n' "$candidate_pid"
    return 0
  fi
  return 1
}

cleanup_stale_state() {
  local active_pid
  if active_pid="$(discover_watcher_pid)"; then
    echo "A watcher exists without a usable PID file (PID $active_pid); leaving state unchanged." >&2
    return 1
  fi
  rm -f "$PID_FILE"
  rmdir "$DAEMON_LOCK" 2>/dev/null || true
}

start_watcher() {
  local quiet=false existing_pid watcher_pid recorded_pid
  if [[ "${1:-}" == "--quiet" ]]; then
    quiet=true
  elif [[ $# -ne 0 ]]; then
    usage >&2
    return 2
  fi

  mkdir -p "$AUTO_SYNC_DIR"
  if existing_pid="$(recorded_watcher_pid)"; then
    $quiet || echo "Auto-sync watcher is already running with PID $existing_pid."
    return 0
  fi
  if existing_pid="$(discover_watcher_pid)"; then
    printf '%s\n' "$existing_pid" >"$PID_FILE"
    $quiet || echo "Recovered auto-sync watcher PID $existing_pid."
    return 0
  fi

  if ! mkdir "$START_LOCK" 2>/dev/null; then
    $quiet || echo "Another shell is starting the auto-sync watcher."
    return 0
  fi
  cleanup_start_lock() {
    rmdir "$START_LOCK" 2>/dev/null || true
  }
  trap cleanup_start_lock RETURN

  cleanup_stale_state
  nohup "$WATCHER" >>"$LOG_FILE" 2>>"$ERROR_LOG_FILE" &
  watcher_pid=$!

  sleep 1
  if ! recorded_pid="$(recorded_watcher_pid)"; then
    echo "Auto-sync watcher failed to start. See $LOG_FILE" >&2
    return 1
  fi
  if [[ "$recorded_pid" != "$watcher_pid" ]]; then
    echo "Auto-sync watcher PID state does not match the started process." >&2
    return 1
  fi
  $quiet || echo "Started auto-sync watcher with PID $watcher_pid."
}

show_status() {
  local watcher_pid
  echo "manager=process"
  if watcher_pid="$(recorded_watcher_pid)"; then
    echo "running=true"
    echo "pid=$watcher_pid"
  elif [[ -f "$PID_FILE" ]]; then
    echo "running=false"
    echo "state=stale_pid_file"
  elif watcher_pid="$(discover_watcher_pid)"; then
    echo "running=true"
    echo "pid=$watcher_pid"
    echo "state=unrecorded_process"
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
  if [[ -s "$ERROR_LOG_FILE" ]]; then
    echo "error_log=$ERROR_LOG_FILE"
    tail -n 12 "$ERROR_LOG_FILE"
  fi
}

stop_watcher() {
  local watcher_pid
  if watcher_pid="$(recorded_watcher_pid)"; then
    :
  elif watcher_pid="$(discover_watcher_pid)"; then
    printf '%s\n' "$watcher_pid" >"$PID_FILE"
  else
    cleanup_stale_state || return 1
    echo "Auto-sync watcher is not running."
    return 0
  fi

  kill -TERM "$watcher_pid"
  for _ in 1 2 3 4 5; do
    if ! process_is_watcher "$watcher_pid"; then
      cleanup_stale_state || return 1
      echo "Stopped auto-sync watcher PID $watcher_pid."
      return 0
    fi
    sleep 1
  done

  echo "Watcher PID $watcher_pid did not stop within five seconds; it may still be finishing a guarded sync." >&2
  return 1
}

case "${1:-}" in
  start)
    shift
    start_watcher "$@"
    ;;
  status)
    shift
    [[ $# -eq 0 ]] || { usage >&2; exit 2; }
    show_status
    ;;
  stop)
    shift
    [[ $# -eq 0 ]] || { usage >&2; exit 2; }
    stop_watcher
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
