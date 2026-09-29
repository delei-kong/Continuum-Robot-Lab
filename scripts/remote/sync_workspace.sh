#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

PROJECT_NAME="$(basename "$PROJECT_ROOT")"
PROJECT_PARENT="$(dirname "$PROJECT_ROOT")"
ARCHIVE_PATH="$REMOTE_STATE_DIR/${PROJECT_NAME}_source.tar.gz"
MANIFEST_PATH="$REMOTE_STATE_DIR/${PROJECT_NAME}_source_manifest.sha256"
REMOTE_ARCHIVE="$REMOTE_PROJECT_PARENT/${PROJECT_NAME}_source.tar.gz"
REMOTE_MANIFEST="$REMOTE_PROJECT_PARENT/${PROJECT_NAME}_source_manifest.sha256"

# Keep source synchronization separate from credentials, caches, datasets, and
# generated experiment outputs. Important run artifacts travel in the opposite
# direction through the dedicated fetch scripts.
: >"$MANIFEST_PATH"
while IFS= read -r -d '' relative_path; do
  normalized_path="${relative_path#./}"
  hash="$(LC_ALL=C shasum -a 256 "$PROJECT_ROOT/$normalized_path" | awk '{print $1}')"
  printf '%s  %s\n' "$hash" "$normalized_path" >>"$MANIFEST_PATH"
done < <(
  cd "$PROJECT_ROOT"
  find . -type f \
    ! -path './.git/*' \
    ! -path './.remote/*' \
    ! -path './.venv/*' \
    ! -path './datasets/*' \
    ! -path './outputs/*' \
    ! -path './runs/*' \
    ! -path './checkpoints/*' \
    ! -path './scripts/remote/config.local.sh' \
    ! -path './source_manifest.sha256' \
    ! -path '*/__pycache__/*' \
    ! -path '*/.pytest_cache/*' \
    ! -path '*/.mypy_cache/*' \
    ! -path '*/.ruff_cache/*' \
    ! -name '*.pyc' \
    ! -name '*.pt' \
    ! -name '*.pth' \
    ! -name '*.mp4' \
    ! -name '.DS_Store' \
    -print0
)

(
  cd "$PROJECT_PARENT"
  # Do not send macOS extended attributes; Linux tar cannot use them and would
  # otherwise emit a warning for every file during extraction.
  LC_ALL=C COPYFILE_DISABLE=1 tar --no-xattrs -czf "$ARCHIVE_PATH" \
    --exclude="$PROJECT_NAME/.git" \
    --exclude="$PROJECT_NAME/.remote" \
    --exclude="$PROJECT_NAME/.venv" \
    --exclude="$PROJECT_NAME/datasets" \
    --exclude="$PROJECT_NAME/outputs" \
    --exclude="$PROJECT_NAME/runs" \
    --exclude="$PROJECT_NAME/checkpoints" \
    --exclude="$PROJECT_NAME/scripts/remote/config.local.sh" \
    --exclude="$PROJECT_NAME/source_manifest.sha256" \
    --exclude='*/__pycache__' \
    --exclude='*/.pytest_cache' \
    --exclude='*/.mypy_cache' \
    --exclude='*/.ruff_cache' \
    --exclude='*.pyc' \
    --exclude='*.pt' \
    --exclude='*.pth' \
    --exclude='*.mp4' \
    --exclude='.DS_Store' \
    "$PROJECT_NAME"
)

remote_exec mkdir -p "$REMOTE_PROJECT_PARENT"
scp "${SCP_ARGS[@]}" "$ARCHIVE_PATH" "$REMOTE_HOST:$REMOTE_ARCHIVE"
scp "${SCP_ARGS[@]}" "$MANIFEST_PATH" "$REMOTE_HOST:$REMOTE_MANIFEST"

remote_exec bash -s -- \
  "$REMOTE_PROJECT_PARENT" "$REMOTE_PROJECT_ROOT" "$REMOTE_ARCHIVE" "$REMOTE_MANIFEST" <<'REMOTE_SCRIPT'
set -euo pipefail
project_parent="$1"
project_root="$2"
archive_path="$3"
manifest_path="$4"

mkdir -p "$project_parent"
tar -xzf "$archive_path" -C "$project_parent"
mv "$manifest_path" "$project_root/source_manifest.sha256"
rm -f "$archive_path"

cd "$project_root"
printf 'remote_workspace_root=%s\n' "$project_root"
sha256sum --check source_manifest.sha256
printf 'workspace_sync_verification=passed\n'
REMOTE_SCRIPT

echo "Synced local workspace to $REMOTE_HOST:$REMOTE_PROJECT_ROOT"
echo "Note: remote-only files are preserved; this script does not perform destructive deletion."
