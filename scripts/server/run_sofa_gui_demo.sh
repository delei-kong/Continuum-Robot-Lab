#!/usr/bin/env bash

# Run the official SoftRobots cable-control demo in the remote XFCE desktop.
set -euo pipefail

SOFA_INSTALL_ROOT="/root/gpufree-data/continuum-runtime/sofa/v25.12.00-python3.10"
SOFA_PYTHON_ENV="/root/gpufree-data/continuum-runtime/envs/sofa-py310"
ACTIVE_ROOT_FILE="$SOFA_INSTALL_ROOT/ACTIVE_ROOT"

# The current workstation exposes its XFCE desktop through Xorg display :20.
export DISPLAY="${DISPLAY:-:20}"

if [[ ! -f "$ACTIVE_ROOT_FILE" ]]; then
  echo "SOFA environment is missing: $ACTIVE_ROOT_FILE" >&2
  echo "Run the SOFA installation workflow before starting this demo." >&2
  exit 3
fi

SOFA_ROOT="$(cat "$ACTIVE_ROOT_FILE")"
RUNSOFA="$SOFA_ROOT/bin/runSofa"
SCENE="$SOFA_ROOT/plugins/SoftRobots/share/sofa/examples/SoftRobots/component/constraint/CableConstraint/DisplacementVsForceControl.py"

if [[ ! -x "$RUNSOFA" ]]; then
  echo "runSofa is not executable: $RUNSOFA" >&2
  exit 3
fi
if [[ ! -f "$SCENE" ]]; then
  echo "SoftRobots demo scene is missing: $SCENE" >&2
  exit 3
fi

display_number="${DISPLAY#:}"
display_number="${display_number%%.*}"
if [[ ! -S "/tmp/.X11-unix/X$display_number" ]]; then
  echo "X11 display socket is unavailable for DISPLAY=$DISPLAY" >&2
  echo "Open the remote desktop first or set DISPLAY to its display number." >&2
  exit 4
fi

export PATH="$SOFA_ROOT/bin:$PATH"
export LD_LIBRARY_PATH="$SOFA_ROOT/lib:$SOFA_ROOT/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$SOFA_PYTHON_ENV/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}"

if [[ "${1:-}" == "--check-only" ]]; then
  echo "display=$DISPLAY"
  echo "sofa_root=$SOFA_ROOT"
  echo "scene=$SCENE"
  glxinfo -B | sed -n \
    -e '/direct rendering/p' \
    -e '/OpenGL vendor string/p' \
    -e '/OpenGL renderer string/p' \
    -e '/OpenGL core profile version string/p'
  echo "gui_check=passed"
  exit 0
fi

echo "Starting the SOFA GUI on DISPLAY=$DISPLAY"
echo "Scene: $SCENE"
echo "Click the SOFA window, then press + or - to change the cable command."
echo "Close the window or press Ctrl+C in this terminal to stop."

exec "$RUNSOFA" \
  -a \
  -l SofaPython3 \
  -l SoftRobots \
  -l SofaImGui \
  -g imgui \
  "$SCENE"
