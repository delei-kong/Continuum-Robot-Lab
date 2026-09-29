#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <run_id>" >&2
  exit 2
fi

RUN_ID="$1"
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid run ID." >&2
  exit 2
fi

LOCAL_RESULTS_ROOT="$PROJECT_ROOT/outputs/sofa_demo"
mkdir -p "$LOCAL_RESULTS_ROOT"
scp "${SCP_ARGS[@]}" -r \
  "$REMOTE_HOST:$REMOTE_PROJECT_ROOT/runs/$RUN_ID" \
  "$LOCAL_RESULTS_ROOT/"

LOCAL_RUN_DIR="$LOCAL_RESULTS_ROOT/$RUN_ID"
test -f "$LOCAL_RUN_DIR/COMPLETE"
test "$(tr -d '[:space:]' <"$LOCAL_RUN_DIR/exit_code")" = "0"
if grep -q '\[ERROR\]' "$LOCAL_RUN_DIR/stdout.log"; then
  echo "SOFA log contains an ERROR entry." >&2
  exit 3
fi

echo "Fetched and verified SOFA demo at $LOCAL_RUN_DIR"
