#!/usr/bin/env bash

# Run the reproducible periodic random-waypoint experiment on the remote workstation.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export TRUNK_INVERSE_CONFIG_REL="configs/trunk_inverse_periodic_random.json"
export TRUNK_INVERSE_STEPS="925"
exec "$SCRIPT_DIR/run_trunk_inverse_tracking.sh" "$@"
