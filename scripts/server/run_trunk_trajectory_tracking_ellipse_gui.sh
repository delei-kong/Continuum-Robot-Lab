#!/usr/bin/env bash

# Run the generic ellipse-trajectory pipeline in the remote XFCE desktop.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="/root/gpufree-share/Continuum-Robot-Lab/workspace"

export TRUNK_INVERSE_CONFIG="$PROJECT_ROOT/configs/trunk_trajectory_tracking_ellipse.json"
export TRUNK_INVERSE_SCENE="$PROJECT_ROOT/src/simulation/scenes/trunk_trajectory_tracking.py"
export TRUNK_INVERSE_STEPS="350"
export TRUNK_INVERSE_GUI_DESCRIPTION=$'Pipeline: closed ellipse trajectory + official SOFA inverse QP\nGreen loop: reference path; yellow marker: loop center; green point: current reference; red point: actual tip; orange line: actual path\nSchedule: settle 1 s, traverse one ellipse in 12 s, hold at the start/finish point for 1 s'
exec "$SCRIPT_DIR/run_trunk_inverse_tracking_gui.sh" "$@"
