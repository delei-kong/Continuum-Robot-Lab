#!/usr/bin/env bash

# Run this script directly inside the remote Linux workstation.
set -euo pipefail

PROJECT_ROOT="/root/gpufree-share/Continuum-Robot-Lab/workspace"
SOFA_INSTALL_ROOT="/root/gpufree-data/continuum-runtime/sofa/v25.12.00-python3.10"
SOFA_PYTHON_ENV="/root/gpufree-data/continuum-runtime/envs/sofa-py310"

RUN_ID="${1:-$(date -u +%Y%m%dT%H%M%SZ)_sofa_cable_demo}"
STEPS="${2:-20}"

if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid run ID: use only letters, digits, dot, underscore, and hyphen." >&2
  exit 2
fi
if [[ ! "$STEPS" =~ ^[1-9][0-9]*$ ]]; then
  echo "Invalid step count: $STEPS" >&2
  exit 2
fi

ACTIVE_ROOT_FILE="$SOFA_INSTALL_ROOT/ACTIVE_ROOT"
if [[ ! -f "$ACTIVE_ROOT_FILE" ]]; then
  echo "SOFA environment is missing: $ACTIVE_ROOT_FILE" >&2
  exit 3
fi

SOFA_ROOT="$(cat "$ACTIVE_ROOT_FILE")"
RUNSOFA="$SOFA_ROOT/bin/runSofa"
SCENE="$SOFA_ROOT/plugins/SoftRobots/share/sofa/examples/SoftRobots/component/constraint/CableConstraint/DisplacementVsForceControl.py"
RUN_DIR="$PROJECT_ROOT/runs/$RUN_ID"

if [[ ! -x "$RUNSOFA" ]]; then
  echo "runSofa is not executable: $RUNSOFA" >&2
  exit 3
fi
if [[ ! -f "$SCENE" ]]; then
  echo "SoftRobots demo scene is missing: $SCENE" >&2
  exit 3
fi
if [[ -e "$RUN_DIR" ]]; then
  echo "Run directory already exists: $RUN_DIR" >&2
  echo "Choose a new run ID to avoid overwriting results." >&2
  exit 4
fi

mkdir -p "$RUN_DIR"
export PATH="$SOFA_ROOT/bin:$PATH"
export LD_LIBRARY_PATH="$SOFA_ROOT/lib:$SOFA_ROOT/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$SOFA_PYTHON_ENV/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}"

printf 'run_id=%s\nsteps=%s\nscene=%s\nrun_dir=%s\n' \
  "$RUN_ID" "$STEPS" "$SCENE" "$RUN_DIR"

set +e
timeout 180 "$RUNSOFA" \
  -g batch \
  -a \
  -n "$STEPS" \
  -l SofaPython3 \
  -l SoftRobots \
  "$SCENE" 2>&1 | tee "$RUN_DIR/stdout.log"
EXIT_CODE=${PIPESTATUS[0]}
set -e

printf '%s\n' "$EXIT_CODE" >"$RUN_DIR/exit_code"
printf '%s\n' "$SCENE" >"$RUN_DIR/scene_path.txt"

if [[ "$EXIT_CODE" -eq 0 ]] && ! grep -q '\[ERROR\]' "$RUN_DIR/stdout.log"; then
  touch "$RUN_DIR/COMPLETE"
  printf '\ndemo_status=complete\nrun_dir=%s\n' "$RUN_DIR"
else
  touch "$RUN_DIR/FAILED"
  printf '\ndemo_status=failed\nexit_code=%s\nrun_dir=%s\n' \
    "$EXIT_CODE" "$RUN_DIR" >&2
  exit 5
fi
