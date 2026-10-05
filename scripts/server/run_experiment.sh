#!/usr/bin/env bash

# Thin remote-workspace boundary for one manifest-driven SOFA experiment.
set -euo pipefail

SOFA_INSTALL_ROOT="/root/gpufree-data/continuum-runtime/sofa/v25.12.00-python3.10"
SOFA_VALIDATION_ROOT="/root/gpufree-data/continuum-runtime/plugins/SofaValidation"
SOFA_PYTHON_ENV="/root/gpufree-data/continuum-runtime/envs/sofa-py310"
PROJECT_ROOT="/root/gpufree-share/Continuum-Robot-Lab/workspace"
ACTIVE_ROOT_FILE="$SOFA_INSTALL_ROOT/ACTIVE_ROOT"
SOFA_VALIDATION_ACTIVE_ROOT_FILE="$SOFA_VALIDATION_ROOT/ACTIVE_ROOT"
RUN_ID="${1:-}"
MANIFEST_JSON="${EXPERIMENT_RUN_MANIFEST:-}"

if [[ -z "$RUN_ID" || ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Usage: $0 <run_id> with EXPERIMENT_RUN_MANIFEST set." >&2
  exit 2
fi
if [[ -z "$MANIFEST_JSON" ]]; then
  echo "EXPERIMENT_RUN_MANIFEST is required." >&2
  exit 2
fi
if [[ ! -f "$ACTIVE_ROOT_FILE" || ! -f "$SOFA_VALIDATION_ACTIVE_ROOT_FILE" ]]; then
  echo "SOFA or SofaValidation runtime is missing." >&2
  exit 3
fi

SOFA_ROOT="$(cat "$ACTIVE_ROOT_FILE")"
SOFA_VALIDATION_INSTALL="$(cat "$SOFA_VALIDATION_ACTIVE_ROOT_FILE")"
SOFA_VALIDATION_LIBRARY="$SOFA_VALIDATION_INSTALL/lib/libSofaValidation.so"
RUNSOFA="$SOFA_ROOT/bin/runSofa"
if [[ ! -x "$RUNSOFA" || ! -f "$SOFA_VALIDATION_LIBRARY" ]]; then
  echo "SOFA runtime is incomplete." >&2
  exit 4
fi

mapfile -t MANIFEST_FIELDS < <("$SOFA_PYTHON_ENV/bin/python" - "$MANIFEST_JSON" "$RUN_ID" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if payload.get("run_id") != sys.argv[2]:
    raise SystemExit("manifest run_id does not match the command argument")
mode = payload.get("mode")
if mode not in {"batch", "gui"}:
    raise SystemExit("manifest mode must be batch or gui")
pipeline = payload.get("pipeline_id")
if pipeline not in {"trunk_tracking", "trunk_forward_data"}:
    raise SystemExit("manifest pipeline is unsupported")
print(pipeline)
print(mode)
PY
) || {
  echo "Invalid EXPERIMENT_RUN_MANIFEST." >&2
  exit 2
}
PIPELINE="${MANIFEST_FIELDS[0]:-}"
MODE="${MANIFEST_FIELDS[1]:-}"
if [[ "$PIPELINE" == "trunk_tracking" ]]; then
  SOFA_INVERSE_LIBRARY="$SOFA_ROOT/plugins/SoftRobots.Inverse/lib/libSoftRobots.Inverse.so"
  if [[ ! -f "$SOFA_INVERSE_LIBRARY" ]]; then
    echo "SOFA inverse runtime is incomplete." >&2
    exit 4
  fi
fi

if [[ "$MODE" == "gui" ]]; then
  export DISPLAY="${DISPLAY:-:20}"
  display_number="${DISPLAY#:}"
  display_number="${display_number%%.*}"
  if [[ ! -S "/tmp/.X11-unix/X$display_number" ]]; then
    echo "X11 display socket is unavailable for DISPLAY=$DISPLAY" >&2
    exit 5
  fi
fi

export PATH="$SOFA_ROOT/bin:$PATH"
export PYTHONPATH="$PROJECT_ROOT/src:$SOFA_PYTHON_ENV/lib/python3.10/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$SOFA_ROOT/lib:$SOFA_ROOT/bin:$SOFA_VALIDATION_INSTALL/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec "$SOFA_PYTHON_ENV/bin/python" -m experiment.runtime \
  --manifest-json "$MANIFEST_JSON" \
  --workspace "$PROJECT_ROOT" \
  --sofa-root "$SOFA_ROOT" \
  --sofa-validation-library "$SOFA_VALIDATION_LIBRARY"
