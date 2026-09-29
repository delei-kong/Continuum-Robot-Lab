#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

RUN_ID="${1:-$(date -u +%Y%m%dT%H%M%SZ)_sofa_trunk_demo}"
STEPS="${SOFA_TRUNK_STEPS:-50}"

if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid run ID: use only letters, digits, dot, underscore, and hyphen." >&2
  exit 2
fi
if [[ ! "$STEPS" =~ ^[1-9][0-9]*$ ]]; then
  echo "SOFA_TRUNK_STEPS must be a positive integer." >&2
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
  "$REMOTE_SOFA_PYTHON_ENV" \
  "$REMOTE_PROJECT_ROOT" \
  "$REMOTE_RUN_DIR" \
  "$RUN_ID" \
  "$STEPS" \
  "$LOCAL_GIT_COMMIT" \
  "$LOCAL_GIT_WORKTREE" <<'REMOTE_SCRIPT'
set -euo pipefail
install_root="$1"
python_env="$2"
project_root="$3"
run_dir="$4"
run_id="$5"
steps="$6"
git_commit="$7"
git_worktree="$8"

active_root_file="$install_root/ACTIVE_ROOT"
if [[ ! -f "$active_root_file" ]]; then
  echo "SOFA is not installed: missing $active_root_file" >&2
  exit 3
fi

sofa_root="$(cat "$active_root_file")"
runsofa="$sofa_root/bin/runSofa"
scene="$project_root/src/simulation/examples/softrobots_trunk/trunk.py"

if [[ ! -x "$runsofa" ]]; then
  echo "runSofa is not executable: $runsofa" >&2
  exit 3
fi
if [[ ! -f "$scene" ]]; then
  echo "The workspace SoftRobots Trunk baseline is missing: $scene" >&2
  exit 4
fi
for mesh_name in trunk.vtk trunk.stl trunk_colli1.stl trunk_colli2.stl; do
  if [[ ! -f "$(dirname "$scene")/mesh/$mesh_name" ]]; then
    echo "Trunk mesh is missing: $mesh_name" >&2
    exit 4
  fi
done
if [[ -e "$run_dir" ]]; then
  echo "Run directory already exists: $run_dir" >&2
  exit 5
fi

mkdir -p "$run_dir"
printf '%s\n' "$scene" >"$run_dir/scene_path.txt"
printf '%s\n' "$sofa_root" >"$run_dir/sofa_root.txt"
sha256sum "$scene" >"$run_dir/scene.sha256"

site_packages="$python_env/lib/python3.10/site-packages"
export PATH="$sofa_root/bin:$PATH"
export PYTHONPATH="$site_packages${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$sofa_root/lib:$sofa_root/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

device_info="$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || true)"
start_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
set +e
timeout 180 "$runsofa" \
  -g batch \
  -a \
  -n "$steps" \
  -l SofaPython3 \
  -l SoftRobots \
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
    "sofa_root": ${sofa_root@Q},
    "steps": int(${steps@Q}),
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

if [[ "$exit_code" -eq 0 ]] && ! grep -q '\[ERROR\]' "$run_dir/stdout.log"; then
  touch "$run_dir/COMPLETE"
  printf 'demo_status=complete\nrun_id=%s\nscene=%s\nsteps=%s\nrun_dir=%s\n' \
    "$run_id" "$scene" "$steps" "$run_dir"
else
  touch "$run_dir/FAILED"
  printf 'demo_status=failed\nrun_id=%s\nscene=%s\nrun_dir=%s\nexit_code=%s\n' \
    "$run_id" "$scene" "$run_dir" "$exit_code" >&2
  tail -n 100 "$run_dir/stdout.log" >&2
  exit 6
fi
REMOTE_SCRIPT
