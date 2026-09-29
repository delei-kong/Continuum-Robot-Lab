#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

RUN_ID="${1:-$(date -u +%Y%m%dT%H%M%SZ)_sine_smoke}"
SESSION_NAME="crl_${RUN_ID//[^a-zA-Z0-9_]/_}"
REMOTE_RUN_DIR="$REMOTE_PROJECT_ROOT/runs/$RUN_ID"
REMOTE_ENTRYPOINT="$REMOTE_PROJECT_ROOT/tests/smoke/remote_gpu/remote_entrypoint.sh"

remote_exec mkdir -p "$REMOTE_RUN_DIR"
remote_exec tmux new-session -d -s "$SESSION_NAME" \
  "$REMOTE_ENTRYPOINT '$REMOTE_CONDA_ENV/bin/python' '$REMOTE_RUN_DIR'"

echo "run_id=$RUN_ID"
echo "tmux_session=$SESSION_NAME"
echo "remote_run_dir=$REMOTE_RUN_DIR"
