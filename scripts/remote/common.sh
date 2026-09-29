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
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$REMOTE_KNOWN_HOSTS"
)

SCP_ARGS=(
  -P "$REMOTE_PORT"
  -i "$REMOTE_IDENTITY"
  -o IdentitiesOnly=yes
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$REMOTE_KNOWN_HOSTS"
)

remote_exec() {
  ssh "${SSH_ARGS[@]}" "$REMOTE_HOST" "$@"
}
