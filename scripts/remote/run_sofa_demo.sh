#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

RUN_ID="${1:-$(date -u +%Y%m%dT%H%M%SZ)_sofa_cable_demo}"
if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid run ID: use only letters, digits, dot, underscore, and hyphen." >&2
  exit 2
fi

REMOTE_RUN_DIR="$REMOTE_PROJECT_ROOT/runs/$RUN_ID"

remote_exec bash -s -- \
  "$REMOTE_SOFA_INSTALL_ROOT" \
  "$REMOTE_SOFA_PYTHON_ENV" \
  "$REMOTE_RUN_DIR" \
  "$RUN_ID" <<'REMOTE_SCRIPT'
set -euo pipefail
install_root="$1"
python_env="$2"
run_dir="$3"
run_id="$4"

active_root_file="$install_root/ACTIVE_ROOT"
if [[ ! -f "$active_root_file" ]]; then
  echo "SOFA is not installed: missing $active_root_file" >&2
  exit 3
fi

sofa_root="$(cat "$active_root_file")"
runsofa="$sofa_root/bin/runSofa"
scene="$(find "$sofa_root/plugins/SoftRobots" -type f \
  -name 'DisplacementVsForceControl.py' -print -quit 2>/dev/null || true)"
if [[ -z "$scene" ]]; then
  scene="$(find "$sofa_root/plugins/SoftRobots" -type f \
    -path '*/CableConstraint/*' -name 'Finger.py' -print -quit 2>/dev/null || true)"
fi
if [[ -z "$scene" ]]; then
  echo "No bundled SoftRobots CableConstraint demo was found." >&2
  exit 4
fi
if [[ -e "$run_dir" ]]; then
  echo "Run directory already exists: $run_dir" >&2
  exit 5
fi

mkdir -p "$run_dir"
printf '%s\n' "$scene" >"$run_dir/scene_path.txt"
printf '%s\n' "$sofa_root" >"$run_dir/sofa_root.txt"

site_packages="$python_env/lib/python3.10/site-packages"
export PATH="$sofa_root/bin:$PATH"
export PYTHONPATH="$site_packages${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$sofa_root/lib:$sofa_root/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

start_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
set +e
timeout 180 "$runsofa" \
  -g batch \
  -a \
  -n 20 \
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
    "steps": 20,
    "gui": "batch",
    "start_utc": ${start_utc@Q},
    "end_utc": ${end_utc@Q},
    "exit_code": $exit_code,
    "python": sys.version,
    "platform": platform.platform(),
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
PY

if [[ "$exit_code" -eq 0 ]] && ! grep -q '\[ERROR\]' "$run_dir/stdout.log"; then
  touch "$run_dir/COMPLETE"
  printf 'demo_status=complete\nrun_id=%s\nscene=%s\nrun_dir=%s\n' \
    "$run_id" "$scene" "$run_dir"
else
  touch "$run_dir/FAILED"
  printf 'demo_status=failed\nrun_id=%s\nscene=%s\nrun_dir=%s\nexit_code=%s\n' \
    "$run_id" "$scene" "$run_dir" "$exit_code" >&2
  tail -n 80 "$run_dir/stdout.log" >&2
  exit 6
fi
REMOTE_SCRIPT
