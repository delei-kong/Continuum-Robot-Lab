#!/usr/bin/env bash

# Run the 25 Hz inverse Trunk target-tracking scene in the remote XFCE desktop.
set -euo pipefail

SOFA_INSTALL_ROOT="/root/gpufree-data/continuum-runtime/sofa/v25.12.00-python3.10"
SOFA_VALIDATION_ROOT="/root/gpufree-data/continuum-runtime/plugins/SofaValidation"
SOFA_PYTHON_ENV="/root/gpufree-data/continuum-runtime/envs/sofa-py310"
PROJECT_ROOT="/root/gpufree-share/Continuum-Robot-Lab/workspace"
ACTIVE_ROOT_FILE="$SOFA_INSTALL_ROOT/ACTIVE_ROOT"
SOFA_VALIDATION_ACTIVE_ROOT_FILE="$SOFA_VALIDATION_ROOT/ACTIVE_ROOT"
RUN_ID="${1:-$(date -u +%Y%m%dT%H%M%SZ)_trunk_inverse_gui}"
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
if [[ -e "$RUN_DIR" ]]; then
  echo "Run directory already exists: $RUN_DIR" >&2
  exit 5
fi

SOFA_ROOT="$(cat "$ACTIVE_ROOT_FILE")"
SOFA_VALIDATION_INSTALL="$(cat "$SOFA_VALIDATION_ACTIVE_ROOT_FILE")"
SOFA_VALIDATION_LIBRARY="$SOFA_VALIDATION_INSTALL/lib/libSofaValidation.so"
SOFA_INVERSE_LIBRARY="$SOFA_ROOT/plugins/SoftRobots.Inverse/lib/libSoftRobots.Inverse.so"
SOFA_IMGUI_LIBRARY_DIR="$SOFA_ROOT/plugins/SofaImGui/lib"
RUNSOFA="$SOFA_ROOT/bin/runSofa"
SCENE="$PROJECT_ROOT/src/simulation/scenes/trunk_inverse_tracking.py"
CONFIG="$PROJECT_ROOT/configs/trunk_inverse_tracking.json"
display_number="${DISPLAY#:}"
display_number="${display_number%%.*}"
if [[ ! -S "/tmp/.X11-unix/X$display_number" ]]; then
  echo "X11 display socket is unavailable for DISPLAY=$DISPLAY" >&2
  exit 6
fi
if [[ ! -x "$RUNSOFA" || ! -f "$SOFA_VALIDATION_LIBRARY" \
  || ! -f "$SOFA_INVERSE_LIBRARY" || ! -f "$SCENE" || ! -f "$CONFIG" ]]; then
  echo "Trunk inverse GUI runtime, scene, or config is missing." >&2
  exit 7
fi

mkdir -p "$RUN_DIR"
export PATH="$SOFA_ROOT/bin:$PATH"
export LD_LIBRARY_PATH="${SOFA_ROOT}/lib:${SOFA_ROOT}/bin:${SOFA_IMGUI_LIBRARY_DIR}:\
${SOFA_VALIDATION_INSTALL}/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$PROJECT_ROOT/src:$SOFA_PYTHON_ENV/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export TRUNK_INVERSE_CONFIG="$CONFIG"
export TRUNK_RUN_DIR="$RUN_DIR"

echo "Starting the 25 Hz inverse Trunk target-tracking scene on DISPLAY=$DISPLAY"
echo "Run ID: $RUN_ID"
echo "Yellow fixed diamond/crosshair: final target [65, -25, 145] mm"
echo "Green moving point: current reference; red point: mapped tip; orange line: tip trajectory"
echo "Schedule: hold 1 s, move to [65, -25, 145] mm in 5 s, then hold 2 s"

set +e
"$RUNSOFA" \
  -a \
  -n 200 \
  -l "$SOFA_VALIDATION_LIBRARY" \
  -l SofaPython3 \
  -l SoftRobots \
  -l SoftRobots.Inverse \
  -l SofaImGui \
  -g imgui \
  "$SCENE" 2>&1 | tee "$RUN_DIR/stdout.log"
exit_code=${PIPESTATUS[0]}
set -e
printf '%s\n' "$exit_code" >"$RUN_DIR/exit_code"
if [[ "$exit_code" -eq 0 ]] && [[ -s "$RUN_DIR/performance.json" ]] \
  && ! grep -q '\[ERROR\]' "$RUN_DIR/stdout.log"; then
  touch "$RUN_DIR/COMPLETE"
  echo "GUI experiment completed: $RUN_DIR"
else
  touch "$RUN_DIR/FAILED"
  echo "GUI experiment failed: $RUN_DIR" >&2
  exit 8
fi
