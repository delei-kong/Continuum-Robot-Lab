#!/usr/bin/env bash

# Publish one immutable, final-evaluated Koopman model package for remote control.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <final_model_output_id>" >&2
  exit 2
fi

MODEL_ID="$1"
if [[ ! "$MODEL_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid final model output ID." >&2
  exit 2
fi

LOCAL_MODEL_DIR="$PROJECT_ROOT/outputs/koopman_models/$MODEL_ID"
if [[ ! -d "$LOCAL_MODEL_DIR" ]]; then
  echo "Local Koopman model output is missing: $LOCAL_MODEL_DIR" >&2
  exit 3
fi

python3 - "$LOCAL_MODEL_DIR" "$MODEL_ID" <<'PY'
import json
import sys
from pathlib import Path

model_dir = Path(sys.argv[1])
model_id = sys.argv[2]
required = (
    "COMPLETE",
    "exit_code",
    "requested_config.json",
    "summary.json",
    "selection.json",
    "models.npz",
)
missing = [name for name in required if not (model_dir / name).is_file()]
if missing:
    raise SystemExit("Final model package is incomplete: " + ", ".join(missing))
if (model_dir / "exit_code").read_text(encoding="utf-8").strip() != "0":
    raise SystemExit("Final model package has a non-zero exit code")
summary = json.loads((model_dir / "summary.json").read_text(encoding="utf-8"))
selection = json.loads((model_dir / "selection.json").read_text(encoding="utf-8"))
selected = summary.get("selected_by_validation")
if (
    summary.get("status") != "complete"
    or summary.get("evaluation_stage") != "final"
    or summary.get("test_evaluated") is not True
    or not isinstance(selected, str)
    or selection.get("evaluation_stage") != "validation"
    or selection.get("selected_by_validation") != selected
):
    raise SystemExit("Only a completed final model selected by validation can be deployed")
requested = json.loads((model_dir / "requested_config.json").read_text(encoding="utf-8"))
if requested.get("output_id") != model_id:
    raise SystemExit("Final model package output ID does not match its directory")
PY

MODEL_STATE_DIR="$REMOTE_STATE_DIR/koopman_model_deploy"
mkdir -p "$MODEL_STATE_DIR"
ARCHIVE_PATH="$MODEL_STATE_DIR/${MODEL_ID}.tar.gz"
MANIFEST_PATH="$MODEL_STATE_DIR/${MODEL_ID}.sha256"
FILE_LIST_PATH="$MODEL_STATE_DIR/${MODEL_ID}.files"
SYNC_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
REMOTE_INCOMING_DIR="$REMOTE_PROJECT_ROOT/outputs/.koopman-model-incoming"
REMOTE_ARCHIVE="$REMOTE_INCOMING_DIR/${MODEL_ID}-${SYNC_ID}.tar.gz"
REMOTE_MANIFEST="$REMOTE_INCOMING_DIR/${MODEL_ID}-${SYNC_ID}.sha256"

build_manifest() {
  local root="$1"
  local output="$2"
  local temporary="${output}.tmp.$$"
  local relative hash
  : >"$temporary"
  while IFS= read -r -d '' relative; do
    relative="${relative#./}"
    hash="$(shasum -a 256 "$root/$relative" | awk '{print $1}')"
    printf '%s  %s\n' "$hash" "$relative" >>"$temporary"
  done < <(cd "$root" && find . -type f -print0)
  LC_ALL=C sort "$temporary" >"$output"
  rm -f "$temporary"
}

build_manifest "$LOCAL_MODEL_DIR" "$MANIFEST_PATH"
sed -E 's/^[0-9a-f]{64}  //' "$MANIFEST_PATH" >"$FILE_LIST_PATH"
(
  cd "$LOCAL_MODEL_DIR"
  LC_ALL=C COPYFILE_DISABLE=1 tar --no-xattrs -czf "$ARCHIVE_PATH" -T "$FILE_LIST_PATH"
)

remote_exec mkdir -p "$REMOTE_INCOMING_DIR"
scp "${SCP_ARGS[@]}" "$ARCHIVE_PATH" "$REMOTE_HOST:$REMOTE_ARCHIVE"
scp "${SCP_ARGS[@]}" "$MANIFEST_PATH" "$REMOTE_HOST:$REMOTE_MANIFEST"

remote_exec bash -s -- \
  "$REMOTE_PROJECT_ROOT/outputs/koopman_models" "$REMOTE_ARCHIVE" \
  "$REMOTE_MANIFEST" "$MODEL_ID" "$SYNC_ID" <<'REMOTE_SCRIPT'
set -euo pipefail
model_root="$1"
archive_path="$2"
incoming_manifest="$3"
model_id="$4"
sync_id="$5"
target="$model_root/$model_id"
staging="$model_root/.${model_id}.staging-${sync_id}"

cleanup() {
  rm -f "$archive_path" "$incoming_manifest"
  rm -rf "$staging"
}
trap cleanup EXIT INT TERM

build_manifest() {
  local root="$1"
  local output="$2"
  local temporary="${output}.tmp.$$"
  local relative hash
  : >"$temporary"
  while IFS= read -r -d '' relative; do
    relative="${relative#./}"
    hash="$(sha256sum "$root/$relative" | awk '{print $1}')"
    printf '%s  %s\n' "$hash" "$relative" >>"$temporary"
  done < <(cd "$root" && find . -type f -print0)
  LC_ALL=C sort "$temporary" >"$output"
  rm -f "$temporary"
}

mkdir -p "$model_root"
if [[ -e "$target" ]]; then
  if [[ ! -d "$target" ]]; then
    echo "Remote model target is not a directory: $target" >&2
    exit 43
  fi
  current_manifest="$(mktemp)"
  trap 'rm -f "$current_manifest"; cleanup' EXIT INT TERM
  build_manifest "$target" "$current_manifest"
  if cmp -s "$current_manifest" "$incoming_manifest"; then
    echo "koopman_model_deploy=already_present"
    exit 0
  fi
  echo "Remote model target already exists with different content: $target" >&2
  exit 43
fi

mkdir -p "$staging"
tar -xzf "$archive_path" -C "$staging"
if [[ ! -f "$staging/COMPLETE" || ! -f "$staging/models.npz" || ! -f "$staging/summary.json" ]]; then
  echo "Incoming Koopman model package is incomplete." >&2
  exit 44
fi
staged_manifest="$(mktemp)"
trap 'rm -f "$staged_manifest"; cleanup' EXIT INT TERM
build_manifest "$staging" "$staged_manifest"
if ! cmp -s "$staged_manifest" "$incoming_manifest"; then
  echo "Incoming Koopman model hash verification failed." >&2
  exit 44
fi
mv "$staging" "$target"
echo "koopman_model_deploy=published"
echo "remote_model_dir=$target"
REMOTE_SCRIPT

echo "Published final Koopman model $MODEL_ID to $REMOTE_PROJECT_ROOT/outputs/koopman_models/$MODEL_ID"
