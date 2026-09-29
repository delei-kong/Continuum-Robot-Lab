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
LOCAL_RESULTS_ROOT="$PROJECT_ROOT/outputs/remote_smoke"
mkdir -p "$LOCAL_RESULTS_ROOT"

scp "${SCP_ARGS[@]}" -r \
  "$REMOTE_HOST:$REMOTE_PROJECT_ROOT/runs/$RUN_ID" \
  "$LOCAL_RESULTS_ROOT/"

echo "Fetched results to $LOCAL_RESULTS_ROOT/$RUN_ID"
python3 "$PROJECT_ROOT/tests/smoke/remote_gpu/verify_run.py" \
  "$LOCAL_RESULTS_ROOT/$RUN_ID" --check-manifest
