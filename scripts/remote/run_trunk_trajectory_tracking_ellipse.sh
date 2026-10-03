#!/usr/bin/env bash

# Run the generic ellipse-trajectory pipeline on the remote workstation.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export TRUNK_INVERSE_CONFIG_REL="configs/trunk_trajectory_tracking_ellipse.json"
export TRUNK_INVERSE_SCENE_REL="src/simulation/scenes/trunk_trajectory_tracking.py"
export TRUNK_INVERSE_STEPS="350"
exec "$SCRIPT_DIR/run_trunk_inverse_tracking.sh" "$@"
