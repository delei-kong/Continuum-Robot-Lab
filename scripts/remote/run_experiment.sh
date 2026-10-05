#!/usr/bin/env bash

# Thin local-to-SSH boundary for one manifest-driven remote experiment.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

RUN_ID="${1:-}"
MANIFEST_JSON="${EXPERIMENT_RUN_MANIFEST:-}"
if [[ -z "$RUN_ID" || ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Usage: $0 <run_id> with EXPERIMENT_RUN_MANIFEST set." >&2
  exit 2
fi
if [[ -z "$MANIFEST_JSON" ]]; then
  echo "EXPERIMENT_RUN_MANIFEST is required." >&2
  exit 2
fi

MANIFEST_B64="$(printf '%s' "$MANIFEST_JSON" | base64 | tr -d '\n')"
remote_exec bash -s -- "$REMOTE_PROJECT_ROOT" "$RUN_ID" "$MANIFEST_B64" <<'REMOTE_SCRIPT'
set -euo pipefail

project_root="$1"
run_id="$2"
manifest_b64="$3"
export EXPERIMENT_RUN_MANIFEST="$(printf '%s' "$manifest_b64" | base64 -d)"
exec bash "$project_root/scripts/server/run_experiment.sh" "$run_id"
REMOTE_SCRIPT
