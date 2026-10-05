#!/usr/bin/env bash

# One controlled entrypoint for the remote PyTorch/GPU smoke lifecycle.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<EOF
Usage: $0 <setup|sync|run|status|verify> [run_id]

Commands:
  setup            create or check the remote PyTorch/CUDA smoke environment
  sync             guarded whole-workspace sync, then validate smoke sources
  run [run_id]     launch one smoke run in a detached remote tmux session
  status <run_id>  report completion state and the tail of the remote log
  verify <run_id>  validate a completed run and write its artifact manifest

Use scripts/remote/fetch_run.sh smoke <run_id> to fetch a verified run.
EOF
}

validate_run_id() {
  local run_id="$1"
  if [[ ! "$run_id" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid run ID." >&2
    return 2
  fi
}

setup_smoke_environment() {
  remote_exec bash -s -- "$REMOTE_PROJECT_ROOT" "$REMOTE_RUNTIME_ROOT" \
    "$REMOTE_CONDA_ENV" <<'REMOTE_SCRIPT'
set -euo pipefail

project_root="$1"
runtime_root="$2"
conda_env="$3"
conda_bin="${CONDA_EXE:-/opt/conda/bin/conda}"
conda_channel="${CONDA_CHANNEL:-https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main}"

if [[ ! -x "$conda_bin" ]]; then
  echo "Conda executable not found at $conda_bin" >&2
  exit 4
fi

mkdir -p "$project_root/tests/smoke/remote_gpu" "$project_root/runs"
mkdir -p "$runtime_root/envs" "$runtime_root/cache/pip"

if [[ ! -x "$conda_env/bin/python" ]]; then
  "$conda_bin" create -y -p "$conda_env" \
    --override-channels \
    --channel "$conda_channel" \
    python=3.11 pip
fi

export PIP_CACHE_DIR="$runtime_root/cache/pip"
"$conda_env/bin/python" -m pip install --upgrade pip
"$conda_env/bin/python" -m pip install torch==2.12.0

"$conda_env/bin/python" - <<'PY'
import json
import torch

result = {
    "torch_version": torch.__version__,
    "cuda_runtime": torch.version.cuda,
    "cuda_available": torch.cuda.is_available(),
    "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
}
print(json.dumps(result, ensure_ascii=False, indent=2))
if not torch.cuda.is_available():
    raise SystemExit("PyTorch installed, but CUDA is not available")
PY
REMOTE_SCRIPT
}

sync_smoke_sources() {
  "$SCRIPT_DIR/sync_workspace.sh"
  remote_exec bash -s -- "$REMOTE_PROJECT_ROOT/tests/smoke/remote_gpu" \
    "$REMOTE_CONDA_ENV/bin/python" <<'REMOTE_SCRIPT'
set -euo pipefail
smoke_dir="$1"
python_executable="$2"

cd "$smoke_dir"
printf 'remote_source_dir=%s\n' "$smoke_dir"
ls -lh train_sine.py remote_entrypoint.sh verify_run.py
bash -n remote_entrypoint.sh
"$python_executable" -m py_compile train_sine.py verify_run.py
printf 'sync_verification=passed\n'
REMOTE_SCRIPT
}

launch_smoke() {
  local run_id="${1:-$(date -u +%Y%m%dT%H%M%SZ)_sine_smoke}"
  local session_name remote_run_dir remote_entrypoint
  validate_run_id "$run_id"
  session_name="crl_${run_id//[^a-zA-Z0-9_]/_}"
  remote_run_dir="$REMOTE_PROJECT_ROOT/runs/$run_id"
  remote_entrypoint="$REMOTE_PROJECT_ROOT/tests/smoke/remote_gpu/remote_entrypoint.sh"

  remote_exec bash -s -- "$remote_run_dir" "$session_name" "$remote_entrypoint" \
    "$REMOTE_CONDA_ENV/bin/python" <<'REMOTE_SCRIPT'
set -euo pipefail
run_dir="$1"
session_name="$2"
remote_entrypoint="$3"
python_executable="$4"

if [[ -e "$run_dir" ]]; then
  echo "Run directory already exists: $run_dir" >&2
  exit 3
fi
if tmux has-session -t "$session_name" 2>/dev/null; then
  echo "tmux session already exists: $session_name" >&2
  exit 3
fi
mkdir -p "$run_dir"
tmux new-session -d -s "$session_name" \
  "'$remote_entrypoint' '$python_executable' '$run_dir'"
REMOTE_SCRIPT

  echo "run_id=$run_id"
  echo "tmux_session=$session_name"
  echo "remote_run_dir=$remote_run_dir"
}

show_smoke_status() {
  local run_id="$1"
  local remote_run_dir="$REMOTE_PROJECT_ROOT/runs/$run_id"
  validate_run_id "$run_id"
  remote_exec bash -s -- "$remote_run_dir" <<'REMOTE_SCRIPT'
set -euo pipefail
run_dir="$1"

if [[ ! -d "$run_dir" ]]; then
  echo "status=missing"
  exit 3
fi
if [[ -f "$run_dir/COMPLETE" ]]; then
  echo "status=complete"
elif [[ -f "$run_dir/FAILED" ]]; then
  echo "status=failed"
else
  echo "status=running_or_pending"
fi
if [[ -f "$run_dir/exit_code" ]]; then
  printf 'exit_code='
  cat "$run_dir/exit_code"
fi
if [[ -f "$run_dir/stdout.log" ]]; then
  tail -n 30 "$run_dir/stdout.log"
fi
REMOTE_SCRIPT
}

verify_smoke_run() {
  local run_id="$1"
  validate_run_id "$run_id"
  remote_exec "$REMOTE_CONDA_ENV/bin/python" \
    "$REMOTE_PROJECT_ROOT/tests/smoke/remote_gpu/verify_run.py" \
    "$REMOTE_PROJECT_ROOT/runs/$run_id" --write-manifest
}

command_name="${1:-}"
case "$command_name" in
  setup)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    setup_smoke_environment
    ;;
  sync)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    sync_smoke_sources
    ;;
  run)
    [[ $# -le 2 ]] || { usage >&2; exit 2; }
    launch_smoke "${2:-}"
    ;;
  status)
    [[ $# -eq 2 ]] || { usage >&2; exit 2; }
    show_smoke_status "$2"
    ;;
  verify)
    [[ $# -eq 2 ]] || { usage >&2; exit 2; }
    verify_smoke_run "$2"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
