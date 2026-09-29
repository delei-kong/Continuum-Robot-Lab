#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

REMOTE_SMOKE_DIR="$REMOTE_PROJECT_ROOT/tests/smoke/remote_gpu"
remote_exec mkdir -p "$REMOTE_SMOKE_DIR" "$REMOTE_PROJECT_ROOT/runs"

scp "${SCP_ARGS[@]}" \
  "$PROJECT_ROOT/tests/smoke/remote_gpu/train_sine.py" \
  "$PROJECT_ROOT/tests/smoke/remote_gpu/remote_entrypoint.sh" \
  "$PROJECT_ROOT/tests/smoke/remote_gpu/verify_run.py" \
  "$REMOTE_HOST:$REMOTE_SMOKE_DIR/"

remote_exec chmod 755 "$REMOTE_SMOKE_DIR/remote_entrypoint.sh"
echo "Synced smoke-test files to $REMOTE_HOST:$REMOTE_SMOKE_DIR"
"$SCRIPT_DIR/verify_sync.sh"
