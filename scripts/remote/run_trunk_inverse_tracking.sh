#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

RUN_ID="${1:-$(date -u +%Y%m%dT%H%M%SZ)_trunk_inverse_tracking}"
STEPS="${TRUNK_INVERSE_STEPS:-200}"
CONFIG_REL="${TRUNK_INVERSE_CONFIG_REL:-configs/trunk_inverse_tracking.json}"
SCENE_REL="${TRUNK_INVERSE_SCENE_REL:-src/simulation/scenes/trunk_inverse_tracking.py}"

if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid run ID: use only letters, digits, dot, underscore, and hyphen." >&2
  exit 2
fi
if [[ ! "$STEPS" =~ ^[1-9][0-9]*$ ]] || (( STEPS < 2 || STEPS > 5000 )); then
  echo "TRUNK_INVERSE_STEPS must be an integer from 2 to 5000." >&2
  exit 2
fi
if [[ ! "$CONFIG_REL" =~ ^configs/[A-Za-z0-9._/-]+\.json$ ]] || [[ "$CONFIG_REL" == *..* ]]; then
  echo "TRUNK_INVERSE_CONFIG_REL must name a JSON file below configs/." >&2
  exit 2
fi
if [[ ! "$SCENE_REL" =~ ^src/simulation/scenes/[A-Za-z0-9._/-]+\.py$ ]] \
  || [[ "$SCENE_REL" == *..* ]]; then
  echo "TRUNK_INVERSE_SCENE_REL must name a Python file below src/simulation/scenes/." >&2
  exit 2
fi

REMOTE_RUN_DIR="$REMOTE_PROJECT_ROOT/runs/$RUN_ID"
LOCAL_GIT_COMMIT="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"
if [[ -n "$(git -C "$PROJECT_ROOT" status --porcelain --untracked-files=normal)" ]]; then
  LOCAL_GIT_WORKTREE="dirty"
else
  LOCAL_GIT_WORKTREE="clean"
fi

remote_exec bash -s -- \
  "$REMOTE_SOFA_INSTALL_ROOT" \
  "$REMOTE_RUNTIME_ROOT/plugins/SofaValidation" \
  "$REMOTE_SOFA_PYTHON_ENV" \
  "$REMOTE_PROJECT_ROOT" \
  "$REMOTE_RUN_DIR" \
  "$RUN_ID" \
  "$STEPS" \
  "$CONFIG_REL" \
  "$SCENE_REL" \
  "$LOCAL_GIT_COMMIT" \
  "$LOCAL_GIT_WORKTREE" <<'REMOTE_SCRIPT'
set -euo pipefail
install_root="$1"
plugin_root="$2"
python_env="$3"
project_root="$4"
run_dir="$5"
run_id="$6"
steps="$7"
config_rel="$8"
scene_rel="$9"
git_commit="${10}"
git_worktree="${11}"

active_root_file="$install_root/ACTIVE_ROOT"
active_plugin_file="$plugin_root/ACTIVE_ROOT"
scene="$project_root/$scene_rel"
config="$project_root/$config_rel"
if [[ ! -f "$active_root_file" ]]; then
  echo "SOFA is not installed: missing $active_root_file" >&2
  exit 3
fi
sofa_root="$(cat "$active_root_file")"
if [[ ! -f "$active_plugin_file" ]]; then
  echo "SofaValidation is not installed: missing $active_plugin_file" >&2
  exit 4
fi
sofa_validation_root="$(cat "$active_plugin_file")"
sofa_validation_library="$sofa_validation_root/lib/libSofaValidation.so"
inverse_library="$sofa_root/plugins/SoftRobots.Inverse/lib/libSoftRobots.Inverse.so"
runsofa="$sofa_root/bin/runSofa"
if [[ ! -x "$runsofa" || ! -f "$sofa_validation_library" \
  || ! -f "$inverse_library" || ! -f "$scene" || ! -f "$config" ]]; then
  echo "Trunk inverse runtime, scene, or config is missing." >&2
  exit 5
fi
if [[ -e "$run_dir" ]]; then
  echo "Run directory already exists: $run_dir" >&2
  exit 6
fi

mkdir -p "$run_dir"
site_packages="$python_env/lib/python3.10/site-packages"
export PATH="$sofa_root/bin:$PATH"
export PYTHONPATH="$project_root/src:$site_packages${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$sofa_root/lib:$sofa_root/bin:$sofa_validation_root/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export TRUNK_INVERSE_CONFIG="$config"
export TRUNK_RUN_DIR="$run_dir"

device_info="$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || true)"
start_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
set +e
timeout 300 "$runsofa" \
  -g batch \
  -a \
  -n "$steps" \
  -l "$sofa_validation_library" \
  -l SofaPython3 \
  -l SoftRobots \
  -l SoftRobots.Inverse \
  "$scene" >"$run_dir/stdout.log" 2>&1
exit_code=$?
set -e
end_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s\n' "$exit_code" >"$run_dir/exit_code"

"$python_env/bin/python" - "$run_dir/metadata.json" <<PY
import json
import platform
import sys

payload = {
    "run_id": ${run_id@Q},
    "scene": ${scene@Q},
    "steps": int(${steps@Q}),
    "config": ${config_rel@Q},
    "scene_relative": ${scene_rel@Q},
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
if [[ -f "$run_dir/trajectory.csv" ]]; then
  row_count="$(awk 'END { print (NR > 0 ? NR - 1 : 0) }' "$run_dir/trajectory.csv")"
fi
if [[ "$exit_code" -eq 0 ]] \
  && [[ "$row_count" -eq "$steps" ]] \
  && [[ -s "$run_dir/performance.json" ]] \
  && ! grep -q '\[ERROR\]' "$run_dir/stdout.log"; then
  touch "$run_dir/COMPLETE"
  printf 'inverse_status=complete\nrun_id=%s\nsteps=%s\nrows=%s\nrun_dir=%s\n' \
    "$run_id" "$steps" "$row_count" "$run_dir"
else
  touch "$run_dir/FAILED"
  printf 'inverse_status=failed\nrun_id=%s\nexit_code=%s\nrows=%s\nrun_dir=%s\n' \
    "$run_id" "$exit_code" "$row_count" "$run_dir" >&2
  tail -n 120 "$run_dir/stdout.log" >&2
  exit 7
fi
REMOTE_SCRIPT
