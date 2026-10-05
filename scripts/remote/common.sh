#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOCAL_CONFIG="$SCRIPT_DIR/config.local.sh"

if [[ ! -f "$LOCAL_CONFIG" ]]; then
  echo "Missing $LOCAL_CONFIG. Copy config.example.sh and fill in the workstation details." >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$LOCAL_CONFIG"

REMOTE_STATE_DIR="$PROJECT_ROOT/.remote"
REMOTE_KNOWN_HOSTS="$REMOTE_STATE_DIR/known_hosts"
mkdir -p "$REMOTE_STATE_DIR"
touch "$REMOTE_KNOWN_HOSTS"
chmod 600 "$REMOTE_KNOWN_HOSTS"

SSH_ARGS=(
  -p "$REMOTE_PORT"
  -i "$REMOTE_IDENTITY"
  -o IdentitiesOnly=yes
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o ServerAliveInterval=5
  -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$REMOTE_KNOWN_HOSTS"
)

SCP_ARGS=(
  -P "$REMOTE_PORT"
  -i "$REMOTE_IDENTITY"
  -o IdentitiesOnly=yes
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o ServerAliveInterval=5
  -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$REMOTE_KNOWN_HOSTS"
)

remote_exec() {
  ssh "${SSH_ARGS[@]}" "$REMOTE_HOST" "$@"
}

build_source_manifest() {
  local output_file="$1"
  local temporary_file="${output_file}.tmp.$$"
  local relative_file normalized_file file_hash

  : >"$temporary_file"
  while IFS= read -r -d '' relative_file; do
    normalized_file="${relative_file#./}"
    case "$normalized_file" in
      datasets/*|outputs/*|runs/*|checkpoints/*|scripts/remote/config.local.sh|source_manifest.sha256|.sync-pause)
        continue
        ;;
    esac
    if [[ "$normalized_file" == *$'\n'* ]]; then
      echo "Source filenames containing newlines are not supported: $normalized_file" >&2
      return 3
    fi
    # git ls-files includes tracked paths removed from the worktree until the
    # deletion is committed. Omit them from the new manifest so the remote
    # sync protocol can move the previous remote copy into .sync-trash/.
    if [[ ! -f "$PROJECT_ROOT/$normalized_file" ]]; then
      continue
    fi
    file_hash="$(LC_ALL=C shasum -a 256 "$PROJECT_ROOT/$normalized_file" | awk '{print $1}')"
    printf '%s  %s\n' "$file_hash" "$normalized_file" >>"$temporary_file"
  done < <(git -C "$PROJECT_ROOT" ls-files -co --exclude-standard -z)

  LC_ALL=C sort "$temporary_file" >"$output_file"
  rm -f "$temporary_file"
}
