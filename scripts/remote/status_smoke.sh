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

remote_exec bash -s -- "$REMOTE_RUN_DIR" <<'REMOTE_SCRIPT'
set -euo pipefail
run_dir="$1"

if [[ ! -d "$run_dir" ]]; then
  echo "status=missing"
  exit 3
fi

if [[ -f "$run_dir/COMPLETE" ]]; then
  echo "status=complete"
elif [[ -f "$run_dir/FAILED" ]]; then
  echo "status=failed"
else
  echo "status=running_or_pending"
fi

if [[ -f "$run_dir/exit_code" ]]; then
  printf 'exit_code='
  cat "$run_dir/exit_code"
fi

if [[ -f "$run_dir/stdout.log" ]]; then
  tail -n 30 "$run_dir/stdout.log"
fi
REMOTE_SCRIPT
