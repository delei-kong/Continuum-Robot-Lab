#!/usr/bin/env bash

# Run the generic line-trajectory pipeline in the remote XFCE desktop.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="/root/gpufree-share/Continuum-Robot-Lab/workspace"

export TRUNK_INVERSE_CONFIG="${TRUNK_INVERSE_CONFIG:-$PROJECT_ROOT/configs/trunk_trajectory_tracking_line.json}"
export TRUNK_INVERSE_SCENE="${TRUNK_INVERSE_SCENE:-$PROJECT_ROOT/src/simulation/scenes/trunk_trajectory_tracking.py}"
export TRUNK_INVERSE_STEPS="${TRUNK_INVERSE_STEPS:-200}"
export TRUNK_INVERSE_GUI_DESCRIPTION="${TRUNK_INVERSE_GUI_DESCRIPTION:-Pipeline: timed line trajectory + official SOFA inverse QP
Green line: reference path; yellow marker: final target; green point: current reference; red point: actual tip; orange line: actual path
Schedule: settle 1 s, move [0, -5, 185] to [65, -25, 145] mm in 5 s, hold 2 s}"
exec "$SCRIPT_DIR/run_trunk_inverse_tracking_gui.sh" "$@"
