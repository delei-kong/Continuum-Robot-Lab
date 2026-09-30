#!/usr/bin/env bash

# Run the first cyclic Trunk experiment in the remote XFCE desktop.
set -euo pipefail

SOFA_INSTALL_ROOT="/root/gpufree-data/continuum-runtime/sofa/v25.12.00-python3.10"
SOFA_VALIDATION_ROOT="/root/gpufree-data/continuum-runtime/plugins/SofaValidation"
CONTINUUM_VIZ_ROOT="/root/gpufree-data/continuum-runtime/plugins/ContinuumRobotLabViz"
SOFA_PYTHON_ENV="/root/gpufree-data/continuum-runtime/envs/sofa-py310"
PROJECT_ROOT="/root/gpufree-share/Continuum-Robot-Lab/workspace"
ACTIVE_ROOT_FILE="$SOFA_INSTALL_ROOT/ACTIVE_ROOT"
SOFA_VALIDATION_ACTIVE_ROOT_FILE="$SOFA_VALIDATION_ROOT/ACTIVE_ROOT"
CONTINUUM_VIZ_ACTIVE_ROOT_FILE="$CONTINUUM_VIZ_ROOT/ACTIVE_ROOT"
RUN_ID="${1:-$(date -u +%Y%m%dT%H%M%SZ)_trunk_cycle_gui}"
RUN_DIR="$PROJECT_ROOT/runs/$RUN_ID"

export DISPLAY="${DISPLAY:-:20}"
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid run ID." >&2
  exit 2
fi
if [[ ! -f "$ACTIVE_ROOT_FILE" ]]; then
  echo "SOFA environment is missing: $ACTIVE_ROOT_FILE" >&2
  exit 3
fi
if [[ ! -f "$SOFA_VALIDATION_ACTIVE_ROOT_FILE" ]]; then
  echo "SofaValidation is missing: $SOFA_VALIDATION_ACTIVE_ROOT_FILE" >&2
  exit 4
fi
if [[ ! -f "$CONTINUUM_VIZ_ACTIVE_ROOT_FILE" ]]; then
  echo "ContinuumRobotLabViz is missing: $CONTINUUM_VIZ_ACTIVE_ROOT_FILE" >&2
  exit 5
fi
if [[ -e "$RUN_DIR" ]]; then
  echo "Run directory already exists: $RUN_DIR" >&2
  exit 6
fi

SOFA_ROOT="$(cat "$ACTIVE_ROOT_FILE")"
SOFA_VALIDATION_INSTALL="$(cat "$SOFA_VALIDATION_ACTIVE_ROOT_FILE")"
SOFA_VALIDATION_LIBRARY="$SOFA_VALIDATION_INSTALL/lib/libSofaValidation.so"
CONTINUUM_VIZ_INSTALL="$(cat "$CONTINUUM_VIZ_ACTIVE_ROOT_FILE")"
CONTINUUM_VIZ_LIBRARY="$CONTINUUM_VIZ_INSTALL/lib/libContinuumRobotLabViz.so"
SOFA_IMGUI_LIBRARY_DIR="$SOFA_ROOT/plugins/SofaImGui/lib"
SOFA_IMGUI_CONFIG_DIR="${XDG_CONFIG_HOME:-/root/.config}/SOFA/config/imgui"
RUNSOFA="$SOFA_ROOT/bin/runSofa"
SCENE="$PROJECT_ROOT/src/simulation/scenes/trunk_cyclic.py"
CONFIG="$PROJECT_ROOT/configs/trunk_cycle_single.json"
display_number="${DISPLAY#:}"
display_number="${display_number%%.*}"
if [[ ! -S "/tmp/.X11-unix/X$display_number" ]]; then
  echo "X11 display socket is unavailable for DISPLAY=$DISPLAY" >&2
  exit 7
fi
if [[ ! -x "$RUNSOFA" || ! -f "$SOFA_VALIDATION_LIBRARY" \
  || ! -f "$CONTINUUM_VIZ_LIBRARY" || ! -f "$SCENE" || ! -f "$CONFIG" ]]; then
  echo "Trunk cycle runtime, scene, or config is missing." >&2
  exit 8
fi

mkdir -p "$RUN_DIR"
mkdir -p "$SOFA_IMGUI_CONFIG_DIR"
printf 'OPEN' >"$SOFA_IMGUI_CONFIG_DIR/Trunk Control Plot.txt"
export PATH="$SOFA_ROOT/bin:$PATH"
export LD_LIBRARY_PATH="${SOFA_ROOT}/lib:${SOFA_ROOT}/bin:${SOFA_IMGUI_LIBRARY_DIR}:\
${SOFA_VALIDATION_INSTALL}/lib:${CONTINUUM_VIZ_INSTALL}/lib\
${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$PROJECT_ROOT/src:$SOFA_PYTHON_ENV/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export TRUNK_CYCLE_CONFIG="$CONFIG"
export TRUNK_RUN_DIR="$RUN_DIR"

echo "Starting the 14-second cyclic Trunk experiment on DISPLAY=$DISPLAY"
echo "Run ID: $RUN_ID"
echo "Blue body: Trunk; red point: mapped tip; controlled cable: cableL0"
echo "After the 1-second settling phase: green point is the trajectory origin; orange line is the tip trajectory"
echo "SofaImGui window 'Trunk Control Plot': live cableL0 command curve"

set +e
"$RUNSOFA" \
  -a \
  -n 1400 \
  -l "$SOFA_VALIDATION_LIBRARY" \
  -l SofaPython3 \
  -l SoftRobots \
  -l SofaImGui \
  -l "$CONTINUUM_VIZ_LIBRARY" \
  -g imgui \
  "$SCENE" 2>&1 | tee "$RUN_DIR/stdout.log"
exit_code=${PIPESTATUS[0]}
set -e
printf '%s\n' "$exit_code" >"$RUN_DIR/exit_code"
if [[ "$exit_code" -eq 0 ]] && ! grep -q '\[ERROR\]' "$RUN_DIR/stdout.log"; then
  touch "$RUN_DIR/COMPLETE"
  echo "GUI experiment completed: $RUN_DIR"
else
  touch "$RUN_DIR/FAILED"
  echo "GUI experiment failed: $RUN_DIR" >&2
  exit 9
fi
