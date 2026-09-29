#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

LOCAL_SMOKE_DIR="$PROJECT_ROOT/tests/smoke/remote_gpu"
REMOTE_SMOKE_DIR="$REMOTE_PROJECT_ROOT/tests/smoke/remote_gpu"
MANIFEST_PATH="$REMOTE_STATE_DIR/smoke_source_manifest.sha256"
FILES=(train_sine.py remote_entrypoint.sh verify_run.py)

: >"$MANIFEST_PATH"
for filename in "${FILES[@]}"; do
  local_path="$LOCAL_SMOKE_DIR/$filename"
  if [[ ! -f "$local_path" ]]; then
    echo "Missing local source file: $local_path" >&2
    exit 3
  fi
  hash="$(LC_ALL=C shasum -a 256 "$local_path" | awk '{print $1}')"
  printf '%s  %s\n' "$hash" "$filename" >>"$MANIFEST_PATH"
done

echo "local_source_dir=$LOCAL_SMOKE_DIR"
cat "$MANIFEST_PATH"

scp "${SCP_ARGS[@]}" "$MANIFEST_PATH" "$REMOTE_HOST:$REMOTE_SMOKE_DIR/source_manifest.sha256"

remote_exec bash -s -- "$REMOTE_SMOKE_DIR" "$REMOTE_CONDA_ENV/bin/python" <<'REMOTE_SCRIPT'
set -euo pipefail
smoke_dir="$1"
python_executable="$2"

cd "$smoke_dir"
printf 'remote_source_dir=%s\n' "$smoke_dir"
ls -lh train_sine.py remote_entrypoint.sh verify_run.py source_manifest.sha256
sha256sum --check source_manifest.sha256
bash -n remote_entrypoint.sh
"$python_executable" -m py_compile train_sine.py verify_run.py
printf 'sync_verification=passed\n'
REMOTE_SCRIPT
