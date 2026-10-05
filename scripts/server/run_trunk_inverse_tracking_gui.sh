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
STEPS="${TRUNK_INVERSE_STEPS:-200}"

export DISPLAY="${DISPLAY:-:20}"
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid run ID." >&2
  exit 2
fi
if [[ ! "$STEPS" =~ ^[1-9][0-9]*$ ]] || (( STEPS < 2 || STEPS > 5000 )); then
  echo "TRUNK_INVERSE_STEPS must be an integer from 2 to 5000." >&2
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
SCENE="${TRUNK_INVERSE_SCENE:-$PROJECT_ROOT/src/simulation/scenes/trunk_inverse_tracking.py}"
CONFIG="${TRUNK_INVERSE_CONFIG:-$PROJECT_ROOT/configs/trunk_inverse_tracking.json}"
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

RUN_FINALIZED=false
finalize_gui_run() {
  local process_exit_code="$1"
  local allow_completed_artifacts="$2"
  local row_count=0

  if [[ "$RUN_FINALIZED" == "true" ]]; then
    return 0
  fi
  RUN_FINALIZED=true

  if [[ -f "$RUN_DIR/trajectory.csv" ]]; then
    row_count="$(awk 'END { print (NR > 0 ? NR - 1 : 0) }' "$RUN_DIR/trajectory.csv")"
  fi
  printf '%s\n' "$process_exit_code" >"$RUN_DIR/process_exit_code"

  if [[ ( "$process_exit_code" -eq 0 || "$allow_completed_artifacts" == "true" ) \
    && "$row_count" -eq "$STEPS" \
    && -s "$RUN_DIR/performance.json" ]] \
    && ! grep -q '\[ERROR\]' "$RUN_DIR/stdout.log"; then
    # A GUI close may deliver a signal after the scene has already emitted all
    # requested records. Preserve that raw process status above, but treat the
    # fully validated experiment as complete for the common artifact contract.
    printf '0\n' >"$RUN_DIR/exit_code"
    touch "$RUN_DIR/COMPLETE"
    return 0
  fi

  printf '%s\n' "$process_exit_code" >"$RUN_DIR/exit_code"
  touch "$RUN_DIR/FAILED"
  return 1
}

handle_gui_signal() {
  local signal_name="$1"
  local signal_exit_code="$2"

  trap - INT TERM HUP
  printf '[INFO] GUI runner received %s; validating produced artifacts.\n' \
    "$signal_name" >>"$RUN_DIR/stdout.log" 2>/dev/null || true
  if finalize_gui_run "$signal_exit_code" true; then
    echo "GUI experiment completed after $signal_name: $RUN_DIR"
    exit 0
  fi
  echo "GUI experiment interrupted by $signal_name: $RUN_DIR" >&2
  exit "$signal_exit_code"
}

trap 'handle_gui_signal INT 130' INT
trap 'handle_gui_signal TERM 143' TERM
trap 'handle_gui_signal HUP 129' HUP

echo "Starting the 25 Hz inverse Trunk target-tracking scene on DISPLAY=$DISPLAY"
echo "Run ID: $RUN_ID"
if [[ -n "${TRUNK_INVERSE_GUI_DESCRIPTION:-}" ]]; then
  printf '%s\n' "$TRUNK_INVERSE_GUI_DESCRIPTION"
else
  echo "Yellow fixed diamond/crosshair: final target [65, -25, 145] mm"
  echo "Green moving point: current reference; red point: mapped tip; orange line: tip trajectory"
  echo "Schedule: hold 1 s, move to [65, -25, 145] mm in 5 s, then hold 2 s"
fi

set +e
"$RUNSOFA" \
  -a \
  -n "$STEPS" \
  -l "$SOFA_VALIDATION_LIBRARY" \
  -l SofaPython3 \
  -l SoftRobots \
  -l SoftRobots.Inverse \
  -l SofaImGui \
  -g imgui \
  "$SCENE" 2>&1 | tee "$RUN_DIR/stdout.log"
exit_code=${PIPESTATUS[0]}
set -e
if finalize_gui_run "$exit_code" false; then
  echo "GUI experiment completed: $RUN_DIR"
else
  echo "GUI experiment failed: $RUN_DIR" >&2
  exit 8
fi
