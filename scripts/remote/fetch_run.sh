#!/usr/bin/env bash

# Fetch and verify one supported remote run without duplicating per-experiment logic.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <profile> <run_id>" >&2
  echo "Profiles: smoke, sofa_demo, trunk_cycle, trunk_forward_data, trunk_inverse_tracking, trajectory_tracking" >&2
  exit 2
fi

PROFILE="$1"
RUN_ID="$2"
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid run ID." >&2
  exit 2
fi

case "$PROFILE" in
  smoke)
    LOCAL_RESULTS_ROOT="$PROJECT_ROOT/outputs/remote_smoke"
    ;;
  sofa_demo)
    LOCAL_RESULTS_ROOT="$PROJECT_ROOT/outputs/sofa_demo"
    ;;
  trunk_cycle)
    LOCAL_RESULTS_ROOT="$PROJECT_ROOT/outputs/trunk_cycle"
    ;;
  trunk_forward_data)
    LOCAL_RESULTS_ROOT="$PROJECT_ROOT/outputs/trunk_forward_data"
    ;;
  trunk_inverse_tracking)
    LOCAL_RESULTS_ROOT="$PROJECT_ROOT/outputs/trunk_inverse_tracking"
    ;;
  trajectory_tracking)
    LOCAL_RESULTS_ROOT="$PROJECT_ROOT/outputs/trajectory_tracking"
    ;;
  *)
    echo "Unsupported fetch profile: $PROFILE" >&2
    exit 2
    ;;
esac

LOCAL_RUN_DIR="$LOCAL_RESULTS_ROOT/$RUN_ID"
if [[ -e "$LOCAL_RUN_DIR" ]]; then
  echo "Local run directory already exists: $LOCAL_RUN_DIR" >&2
  exit 3
fi

remote_exec bash -s -- "$REMOTE_PROJECT_ROOT/runs/$RUN_ID" "$PROFILE" <<'REMOTE_SCRIPT'
set -euo pipefail

run_dir="$1"
profile="$2"
if [[ ! -d "$run_dir" ]]; then
  echo "Remote run directory does not exist: $run_dir" >&2
  exit 4
fi
if [[ ! -f "$run_dir/COMPLETE" ]] || [[ -e "$run_dir/FAILED" ]]; then
  echo "Remote run is not a verified success: $run_dir" >&2
  exit 4
fi
if [[ ! -f "$run_dir/exit_code" ]] \
  || [[ "$(tr -d '[:space:]' <"$run_dir/exit_code")" != "0" ]]; then
  echo "Remote run has no successful exit code: $run_dir" >&2
  exit 4
fi
if [[ ! -s "$run_dir/stdout.log" ]] || grep -q '\[ERROR\]' "$run_dir/stdout.log"; then
  echo "Remote run log is missing or contains an ERROR entry: $run_dir" >&2
  exit 4
fi

case "$profile" in
  smoke|sofa_demo)
    ;;
  trunk_cycle)
    test -s "$run_dir/trajectory.csv"
    ;;
  trunk_forward_data)
    test -s "$run_dir/episode.csv"
    test -s "$run_dir/effective_config.json"
    test -s "$run_dir/metadata.json"
    ;;
  trunk_inverse_tracking|trajectory_tracking)
    test -s "$run_dir/trajectory.csv"
    test -s "$run_dir/performance.json"
    ;;
  *)
    echo "Unsupported fetch profile: $profile" >&2
    exit 4
    ;;
esac
REMOTE_SCRIPT

mkdir -p "$LOCAL_RESULTS_ROOT"
scp "${SCP_ARGS[@]}" -r \
  "$REMOTE_HOST:$REMOTE_PROJECT_ROOT/runs/$RUN_ID" \
  "$LOCAL_RESULTS_ROOT/"

test -f "$LOCAL_RUN_DIR/COMPLETE"
test ! -e "$LOCAL_RUN_DIR/FAILED"
test "$(tr -d '[:space:]' <"$LOCAL_RUN_DIR/exit_code")" = "0"
test -s "$LOCAL_RUN_DIR/stdout.log"
if grep -q '\[ERROR\]' "$LOCAL_RUN_DIR/stdout.log"; then
  echo "SOFA log contains an ERROR entry." >&2
  exit 4
fi

case "$PROFILE" in
  smoke)
    python3 "$PROJECT_ROOT/tests/smoke/remote_gpu/verify_run.py" \
      "$LOCAL_RUN_DIR" --check-manifest
    ;;
  trunk_cycle)
    test -s "$LOCAL_RUN_DIR/trajectory.csv"
    ;;
  trunk_forward_data)
    test -s "$LOCAL_RUN_DIR/episode.csv"
    test -s "$LOCAL_RUN_DIR/effective_config.json"
    test -s "$LOCAL_RUN_DIR/metadata.json"
    ;;
  trunk_inverse_tracking|trajectory_tracking)
    test -s "$LOCAL_RUN_DIR/trajectory.csv"
    test -s "$LOCAL_RUN_DIR/performance.json"
    ;;
  sofa_demo)
    ;;
esac

echo "Fetched and verified $PROFILE run at $LOCAL_RUN_DIR"
