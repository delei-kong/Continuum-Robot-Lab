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
REMOTE_RUN_DIR="$REMOTE_PROJECT_ROOT/runs/$RUN_ID"
REMOTE_VERIFIER="$REMOTE_PROJECT_ROOT/tests/smoke/remote_gpu/verify_run.py"

remote_exec "$REMOTE_CONDA_ENV/bin/python" "$REMOTE_VERIFIER" \
  "$REMOTE_RUN_DIR" --write-manifest
