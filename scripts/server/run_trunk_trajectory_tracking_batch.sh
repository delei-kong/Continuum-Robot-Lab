#!/usr/bin/env bash

# Run one configured trajectory experiment directly inside the remote SOFA runtime.
set -euo pipefail

SOFA_INSTALL_ROOT="/root/gpufree-data/continuum-runtime/sofa/v25.12.00-python3.10"
SOFA_VALIDATION_ROOT="/root/gpufree-data/continuum-runtime/plugins/SofaValidation"
SOFA_PYTHON_ENV="/root/gpufree-data/continuum-runtime/envs/sofa-py310"
PROJECT_ROOT="/root/gpufree-share/Continuum-Robot-Lab/workspace"
ACTIVE_ROOT_FILE="$SOFA_INSTALL_ROOT/ACTIVE_ROOT"
SOFA_VALIDATION_ACTIVE_ROOT_FILE="$SOFA_VALIDATION_ROOT/ACTIVE_ROOT"
RUN_ID="${1:-}"
STEPS="${TRUNK_INVERSE_STEPS:-200}"
SCENE="${TRUNK_INVERSE_SCENE:-$PROJECT_ROOT/src/simulation/scenes/trunk_trajectory_tracking.py}"
CONFIG="${TRUNK_INVERSE_CONFIG:-$PROJECT_ROOT/configs/trunk_trajectory_tracking_line.json}"
RUN_DIR="$PROJECT_ROOT/runs/$RUN_ID"

if [[ -z "$RUN_ID" || ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Usage: $0 <run_id>" >&2
  exit 2
fi
if [[ ! "$STEPS" =~ ^[1-9][0-9]*$ ]] || (( STEPS < 2 || STEPS > 5000 )); then
  echo "TRUNK_INVERSE_STEPS must be an integer from 2 to 5000." >&2
  exit 2
fi
if [[ ! -f "$ACTIVE_ROOT_FILE" || ! -f "$SOFA_VALIDATION_ACTIVE_ROOT_FILE" ]]; then
  echo "SOFA or SofaValidation runtime is missing." >&2
  exit 3
fi
if [[ -e "$RUN_DIR" ]]; then
  echo "Run directory already exists: $RUN_DIR" >&2
  exit 5
fi

SOFA_ROOT="$(cat "$ACTIVE_ROOT_FILE")"
SOFA_VALIDATION_INSTALL="$(cat "$SOFA_VALIDATION_ACTIVE_ROOT_FILE")"
SOFA_VALIDATION_LIBRARY="$SOFA_VALIDATION_INSTALL/lib/libSofaValidation.so"
RUNSOFA="$SOFA_ROOT/bin/runSofa"
if [[ ! -x "$RUNSOFA" || ! -f "$SOFA_VALIDATION_LIBRARY" \
  || ! -f "$SCENE" || ! -f "$CONFIG" ]]; then
  echo "SOFA runtime, scene, or config is missing." >&2
  exit 6
fi

mkdir -p "$RUN_DIR"
export PATH="$SOFA_ROOT/bin:$PATH"
export PYTHONPATH="$PROJECT_ROOT/src:$SOFA_PYTHON_ENV/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$SOFA_ROOT/lib:$SOFA_ROOT/bin:$SOFA_VALIDATION_INSTALL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TRUNK_INVERSE_CONFIG="$CONFIG"
export TRUNK_RUN_DIR="$RUN_DIR"

device_info="$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || true)"
start_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
set +e
timeout 300 "$RUNSOFA" \
  -g batch \
  -a \
  -n "$STEPS" \
  -l "$SOFA_VALIDATION_LIBRARY" \
  -l SofaPython3 \
  -l SoftRobots \
  -l SoftRobots.Inverse \
  "$SCENE" >"$RUN_DIR/stdout.log" 2>&1
exit_code=$?
set -e
end_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s\n' "$exit_code" >"$RUN_DIR/exit_code"

git_commit="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null || true)"
git_worktree="clean"
if [[ -n "$(git -C "$PROJECT_ROOT" status --porcelain --untracked-files=normal 2>/dev/null)" ]]; then
  git_worktree="dirty"
fi
"$SOFA_PYTHON_ENV/bin/python" - "$RUN_DIR/metadata.json" <<PY
import json
import platform
import sys

payload = {
    "run_id": ${RUN_ID@Q},
    "scene": ${SCENE@Q},
    "steps": int(${STEPS@Q}),
    "config": ${CONFIG@Q},
    "gui": "batch",
    "start_utc": ${start_utc@Q},
    "end_utc": ${end_utc@Q},
    "exit_code": $exit_code,
    "git_commit": ${git_commit@Q},
    "git_worktree": ${git_worktree@Q},
    "device": ${device_info@Q},
    "python": sys.version,
    "platform": platform.platform(),
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
PY

row_count=0
if [[ -f "$RUN_DIR/trajectory.csv" ]]; then
  row_count="$(awk 'END { print (NR > 0 ? NR - 1 : 0) }' "$RUN_DIR/trajectory.csv")"
fi
if [[ "$exit_code" -eq 0 ]] \
  && [[ "$row_count" -eq "$STEPS" ]] \
  && [[ -s "$RUN_DIR/performance.json" ]] \
  && ! grep -q '\[ERROR\]' "$RUN_DIR/stdout.log"; then
  touch "$RUN_DIR/COMPLETE"
  printf 'inverse_status=complete\nrun_id=%s\nsteps=%s\nrows=%s\nrun_dir=%s\n' \
    "$RUN_ID" "$STEPS" "$row_count" "$RUN_DIR"
else
  touch "$RUN_DIR/FAILED"
  printf 'inverse_status=failed\nrun_id=%s\nexit_code=%s\nrows=%s\nrun_dir=%s\n' \
    "$RUN_ID" "$exit_code" "$row_count" "$RUN_DIR" >&2
  tail -n 120 "$RUN_DIR/stdout.log" >&2
  exit 7
fi
