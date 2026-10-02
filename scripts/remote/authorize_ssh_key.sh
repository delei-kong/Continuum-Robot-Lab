#!/usr/bin/env bash

# Restore passwordless SSH access by installing the configured public key.
# The remote account password is entered interactively by the user and is
# never accepted as an argument or stored by this script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_CONFIG="$SCRIPT_DIR/config.local.sh"

if [[ ! -f "$LOCAL_CONFIG" ]]; then
  echo "Missing $LOCAL_CONFIG. Copy config.example.sh and fill in the workstation details." >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$LOCAL_CONFIG"

if [[ -z "${REMOTE_HOST:-}" || -z "${REMOTE_PORT:-}" || -z "${REMOTE_IDENTITY:-}" ]]; then
  echo "REMOTE_HOST, REMOTE_PORT, and REMOTE_IDENTITY must be configured." >&2
  exit 3
fi
if [[ ! "$REMOTE_PORT" =~ ^[1-9][0-9]{0,4}$ ]] || (( REMOTE_PORT > 65535 )); then
  echo "Invalid REMOTE_PORT: $REMOTE_PORT" >&2
  exit 3
fi
if [[ ! -f "$REMOTE_IDENTITY" ]]; then
  echo "Configured private key does not exist: $REMOTE_IDENTITY" >&2
  exit 4
fi
if ! command -v ssh-keygen >/dev/null 2>&1; then
  echo "ssh-keygen is not installed." >&2
  exit 5
fi
if ! command -v ssh-copy-id >/dev/null 2>&1; then
  echo "ssh-copy-id is not installed." >&2
  exit 5
fi

PUBLIC_KEY="${REMOTE_IDENTITY}.pub"
if [[ ! -f "$PUBLIC_KEY" ]]; then
  TEMP_PUBLIC_KEY="${PUBLIC_KEY}.tmp.$$"
  cleanup() {
    rm -f "$TEMP_PUBLIC_KEY"
  }
  trap cleanup EXIT
  umask 077
  ssh-keygen -y -f "$REMOTE_IDENTITY" >"$TEMP_PUBLIC_KEY"
  chmod 644 "$TEMP_PUBLIC_KEY"
  mv "$TEMP_PUBLIC_KEY" "$PUBLIC_KEY"
  trap - EXIT
  echo "Created public key: $PUBLIC_KEY"
fi

echo "Installing $PUBLIC_KEY on $REMOTE_HOST port $REMOTE_PORT"
echo "Enter the remote account password when ssh-copy-id prompts for it."
ssh-copy-id -i "$PUBLIC_KEY" -p "$REMOTE_PORT" "$REMOTE_HOST"

echo "Public key installed; checking passwordless connection."
"$SCRIPT_DIR/check_connection.sh"
