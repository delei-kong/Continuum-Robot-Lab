#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

PROJECT_NAME="$(basename "$PROJECT_ROOT")"
PROJECT_PARENT="$(dirname "$PROJECT_ROOT")"
ARCHIVE_PATH="$REMOTE_STATE_DIR/${PROJECT_NAME}_source.tar.gz"
MANIFEST_PATH="$REMOTE_STATE_DIR/${PROJECT_NAME}_source_manifest.sha256"
ARCHIVE_FILE_LIST="$REMOTE_STATE_DIR/${PROJECT_NAME}_source_files.txt"
LOCAL_SYNC_LOCK="$REMOTE_STATE_DIR/workspace_sync.lock"
SYNC_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
REMOTE_INCOMING_DIR="$REMOTE_PROJECT_PARENT/.sync-incoming"
REMOTE_ARCHIVE="$REMOTE_INCOMING_DIR/${PROJECT_NAME}_${SYNC_ID}.tar.gz"
REMOTE_MANIFEST="$REMOTE_INCOMING_DIR/${PROJECT_NAME}_${SYNC_ID}.sha256"

if ! mkdir "$LOCAL_SYNC_LOCK" 2>/dev/null; then
  echo "A local workspace sync is already in progress." >&2
  exit 43
fi

cleanup_local_lock() {
  rmdir "$LOCAL_SYNC_LOCK" 2>/dev/null || true
}
trap cleanup_local_lock EXIT INT TERM

# Keep source synchronization separate from credentials, caches, datasets, and
# generated experiment outputs. Important run outputs travel in the opposite
# direction through the dedicated fetch scripts.
build_source_manifest "$MANIFEST_PATH"

: >"$ARCHIVE_FILE_LIST"
while IFS= read -r manifest_line; do
  relative_file="${manifest_line#*  }"
  printf '%s/%s\n' "$PROJECT_NAME" "$relative_file" >>"$ARCHIVE_FILE_LIST"
done <"$MANIFEST_PATH"

(
  cd "$PROJECT_PARENT"
  # Do not send macOS extended attributes; Linux tar cannot use them and would
  # otherwise emit a warning for every file during extraction.
  LC_ALL=C COPYFILE_DISABLE=1 tar --no-xattrs -czf "$ARCHIVE_PATH" \
    -T "$ARCHIVE_FILE_LIST"
)

remote_exec mkdir -p "$REMOTE_INCOMING_DIR"
scp "${SCP_ARGS[@]}" "$ARCHIVE_PATH" "$REMOTE_HOST:$REMOTE_ARCHIVE"
scp "${SCP_ARGS[@]}" "$MANIFEST_PATH" "$REMOTE_HOST:$REMOTE_MANIFEST"

remote_exec bash -s -- \
  "$REMOTE_PROJECT_PARENT" "$REMOTE_PROJECT_ROOT" "$REMOTE_ARCHIVE" \
  "$REMOTE_MANIFEST" "$SYNC_ID" <<'REMOTE_SCRIPT'
set -euo pipefail
project_parent="$1"
project_root="$2"
archive_path="$3"
incoming_manifest="$4"
sync_id="$5"
remote_lock="$project_parent/.workspace-sync.lock"

if ! mkdir "$remote_lock" 2>/dev/null; then
  echo "A remote workspace sync is already in progress." >&2
  exit 43
fi

cleanup_remote_sync() {
  rm -f "$archive_path" "$incoming_manifest"
  rmdir "$remote_lock" 2>/dev/null || true
}
trap cleanup_remote_sync EXIT INT TERM

if [[ -e "$project_root/.sync-pause" ]]; then
  echo "Remote synchronization is paused by $project_root/.sync-pause" >&2
  exit 44
fi

build_remote_manifest() {
  local root="$1"
  local output_file="$2"
  local temporary_file="${output_file}.tmp.$$"
  local relative_file normalized_file file_hash

  : >"$temporary_file"
  while IFS= read -r -d '' relative_file; do
    normalized_file="${relative_file#./}"
    file_hash="$(sha256sum "$root/$normalized_file" | awk '{print $1}')"
    printf '%s  %s\n' "$file_hash" "$normalized_file" >>"$temporary_file"
  done < <(
    cd "$root"
    find . -type f \
      ! -path './.git/*' \
      ! -path './.remote/*' \
      ! -path './.venv/*' \
      ! -path './datasets/*' \
      ! -path './outputs/*' \
      ! -path './artifacts/*' \
      ! -path './data/*' \
      ! -path './runs/*' \
      ! -path './checkpoints/*' \
      ! -path './scripts/remote/config.local.sh' \
      ! -path './source_manifest.sha256' \
      ! -path './.sync-pause' \
      ! -path '*/__pycache__/*' \
      ! -path '*/.pytest_cache/*' \
      ! -path '*/.ipynb_checkpoints/*' \
      ! -path '*/.mypy_cache/*' \
      ! -path '*/.ruff_cache/*' \
      ! -name '*.pyc' \
      ! -name '*.pt' \
      ! -name '*.pth' \
      ! -name '*.mp4' \
      ! -name '.DS_Store' \
      ! -name '._*' \
      -print0
  )

  LC_ALL=C sort "$temporary_file" >"$output_file"
  rm -f "$temporary_file"
}

mkdir -p "$project_parent"
current_manifest="$(mktemp)"
old_manifest="$(mktemp)"
old_paths="$(mktemp)"
new_paths="$(mktemp)"
trap 'rm -f "$current_manifest" "$old_manifest" "$old_paths" "$new_paths"; cleanup_remote_sync' EXIT INT TERM

if [[ -f "$project_root/source_manifest.sha256" ]]; then
  build_remote_manifest "$project_root" "$current_manifest"
  LC_ALL=C sort "$project_root/source_manifest.sha256" >"$old_manifest"
  if ! cmp -s "$old_manifest" "$current_manifest"; then
    echo "REMOTE_SOURCE_DRIFT: remote source differs from the last successful sync." >&2
    diff -u "$old_manifest" "$current_manifest" | sed -n '1,120p' >&2 || true
    exit 42
  fi
elif [[ -d "$project_root" ]]; then
  build_remote_manifest "$project_root" "$current_manifest"
  if [[ -s "$current_manifest" ]]; then
    echo "REMOTE_SOURCE_DRIFT: remote source exists without a synchronization baseline." >&2
    exit 42
  fi
fi

# Preserve files removed locally in a timestamped remote trash directory. Only
# paths from the previous verified manifest are eligible, and traversal paths
# are rejected before any move occurs.
if [[ -s "$old_manifest" ]]; then
  sed -E 's/^[0-9a-f]{64}  //' "$old_manifest" | LC_ALL=C sort >"$old_paths"
  sed -E 's/^[0-9a-f]{64}  //' "$incoming_manifest" | LC_ALL=C sort >"$new_paths"
  trash_root="$project_parent/.sync-trash/$sync_id"
  while IFS= read -r obsolete_path; do
    [[ -n "$obsolete_path" ]] || continue
    case "$obsolete_path" in
      /*|..|../*|*/../*)
        echo "Unsafe obsolete path in manifest: $obsolete_path" >&2
        exit 45
        ;;
    esac
    source_path="$project_root/$obsolete_path"
    if [[ -f "$source_path" || -L "$source_path" ]]; then
      mkdir -p "$trash_root/$(dirname "$obsolete_path")"
      mv -- "$source_path" "$trash_root/$obsolete_path"
    fi
  done < <(comm -23 "$old_paths" "$new_paths")
fi

tar -xzf "$archive_path" -C "$project_parent"
mv "$incoming_manifest" "$project_root/source_manifest.sha256"

cd "$project_root"
printf 'remote_workspace_root=%s\n' "$project_root"
sha256sum --check source_manifest.sha256
printf 'workspace_sync_verification=passed\n'
REMOTE_SCRIPT

echo "Synced local workspace to $REMOTE_HOST:$REMOTE_PROJECT_ROOT"
echo "Remote source drift is checked before every upload is applied."
