#!/usr/bin/env bash

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

AUTO_SYNC_DIR="$REMOTE_STATE_DIR/auto_sync"
DAEMON_LOCK="$AUTO_SYNC_DIR/daemon.lock"
PID_FILE="$AUTO_SYNC_DIR/pid"
STATUS_FILE="$AUTO_SYNC_DIR/status"
LAST_SIGNATURE_FILE="$AUTO_SYNC_DIR/last_success_signature"
CANDIDATE_MANIFEST="$AUTO_SYNC_DIR/candidate_manifest.sha256"
POLL_SECONDS="${AUTO_SYNC_POLL_SECONDS:-3}"
RETRY_SECONDS="${AUTO_SYNC_RETRY_SECONDS:-30}"

mkdir -p "$AUTO_SYNC_DIR"
if ! mkdir "$DAEMON_LOCK" 2>/dev/null; then
  echo "Auto-sync watcher is already running." >&2
  exit 0
fi

cleanup_watcher() {
  rm -f "$PID_FILE"
  rmdir "$DAEMON_LOCK" 2>/dev/null || true
}
trap cleanup_watcher EXIT INT TERM
printf '%s\n' "$$" >"$PID_FILE"

write_status() {
  printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" "$1" >"$STATUS_FILE"
}

calculate_signature() {
  build_source_manifest "$CANDIDATE_MANIFEST" || return 1
  LC_ALL=C shasum -a 256 "$CANDIDATE_MANIFEST" | awk '{print $1}'
}

last_success_signature=""
if [[ -f "$LAST_SIGNATURE_FILE" ]]; then
  last_success_signature="$(tr -d '[:space:]' <"$LAST_SIGNATURE_FILE")"
fi

observed_signature=""
stable_observations=0
blocked_signature=""
last_retry_epoch=0
write_status "watching"
echo "Auto-sync watcher started for $PROJECT_ROOT"

while true; do
  current_signature="$(calculate_signature 2>/dev/null || true)"
  if [[ -z "$current_signature" ]]; then
    write_status "local_manifest_failed"
    sleep "$POLL_SECONDS"
    continue
  fi

  if [[ "$current_signature" == "$observed_signature" ]]; then
    stable_observations=$((stable_observations + 1))
  else
    observed_signature="$current_signature"
    stable_observations=1
    blocked_signature=""
  fi

  if [[ "$stable_observations" -ge 2 && "$current_signature" != "$last_success_signature" ]]; then
    if [[ "$current_signature" == "$blocked_signature" ]]; then
      sleep "$POLL_SECONDS"
      continue
    fi

    current_epoch="$(date +%s)"
    if (( current_epoch - last_retry_epoch < RETRY_SECONDS )); then
      sleep "$POLL_SECONDS"
      continue
    fi
    last_retry_epoch="$current_epoch"
    write_status "syncing"
    echo "$(date '+%Y-%m-%d %H:%M:%S %z') | local source change detected"

    if "$SCRIPT_DIR/sync_workspace.sh"; then
      sync_exit_code=0
    else
      sync_exit_code=$?
    fi
    if [[ "$sync_exit_code" -eq 0 ]]; then
      printf '%s\n' "$current_signature" >"$LAST_SIGNATURE_FILE"
      last_success_signature="$current_signature"
      write_status "synced"
    elif [[ "$sync_exit_code" -eq 42 || "$sync_exit_code" -eq 44 || "$sync_exit_code" -eq 45 ]]; then
      blocked_signature="$current_signature"
      write_status "blocked_remote_guard_exit_$sync_exit_code"
      echo "Auto-sync paused for the current local state; resolve the remote guard before retrying." >&2
    else
      write_status "retry_pending_exit_$sync_exit_code"
      echo "Auto-sync failed with exit code $sync_exit_code; retrying later." >&2
    fi
  fi

  sleep "$POLL_SECONDS"
done
