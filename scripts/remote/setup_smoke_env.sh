#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

remote_exec bash -s -- "$REMOTE_PROJECT_ROOT" "$REMOTE_RUNTIME_ROOT" "$REMOTE_CONDA_ENV" <<'REMOTE_SCRIPT'
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
