#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

remote_exec "printf 'connection_ok\\n'; whoami; nvidia-smi --query-gpu=name,memory.total --format=csv,noheader"
