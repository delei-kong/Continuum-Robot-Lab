#!/usr/bin/env bash

# Run the periodic random-waypoint scene in the remote XFCE desktop.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="/root/gpufree-share/Continuum-Robot-Lab/workspace"

export TRUNK_INVERSE_CONFIG="$PROJECT_ROOT/configs/trunk_inverse_periodic_random.json"
export TRUNK_INVERSE_STEPS="925"
export TRUNK_INVERSE_GUI_DESCRIPTION=$'Fixed colored markers: three seeded random waypoints\nGreen point: current reference; red point: mapped tip; orange line: tip trajectory\nSchedule: settle 1 s, then visit 3 waypoints twice; each transition 5 s and hold 1 s'
exec "$SCRIPT_DIR/run_trunk_inverse_tracking_gui.sh" "$@"
