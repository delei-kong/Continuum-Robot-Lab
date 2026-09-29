#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

SOFA_ARCHIVE_NAME="SOFA_v${REMOTE_SOFA_VERSION}_Linux-Python_${REMOTE_SOFA_PYTHON_VERSION}.zip"
SOFA_ARCHIVE_SHA256="c88f6d23f8494b9ed100dffda1e73daadffc5428c395f9f64e36977fa3e6731a"
LOCAL_ARCHIVE="${1:-$REMOTE_STATE_DIR/cache/$SOFA_ARCHIVE_NAME}"
REMOTE_DOWNLOAD_DIR="$REMOTE_RUNTIME_ROOT/downloads"
REMOTE_ARCHIVE="$REMOTE_DOWNLOAD_DIR/$SOFA_ARCHIVE_NAME"

if [[ ! -f "$LOCAL_ARCHIVE" ]]; then
  echo "Missing SOFA archive: $LOCAL_ARCHIVE" >&2
  echo "Download the official archive, then pass its local path to this script." >&2
  exit 3
fi

local_hash="$(LC_ALL=C shasum -a 256 "$LOCAL_ARCHIVE" | awk '{print $1}')"
if [[ "$local_hash" != "$SOFA_ARCHIVE_SHA256" ]]; then
  echo "SOFA archive checksum mismatch." >&2
  echo "expected=$SOFA_ARCHIVE_SHA256" >&2
  echo "actual=$local_hash" >&2
  exit 4
fi

echo "local_archive=$LOCAL_ARCHIVE"
echo "archive_sha256=$local_hash"
remote_exec mkdir -p "$REMOTE_DOWNLOAD_DIR" "$REMOTE_SOFA_INSTALL_ROOT"
if remote_exec test -f "$REMOTE_ARCHIVE"; then
  remote_hash="$(remote_exec sha256sum "$REMOTE_ARCHIVE" | awk '{print $1}')"
else
  remote_hash="missing"
fi
if [[ "$remote_hash" == "$SOFA_ARCHIVE_SHA256" ]]; then
  echo "Reusing verified remote archive: $REMOTE_ARCHIVE"
else
  scp "${SCP_ARGS[@]}" "$LOCAL_ARCHIVE" "$REMOTE_HOST:$REMOTE_ARCHIVE"
fi

remote_exec bash -s -- \
  "$REMOTE_ARCHIVE" \
  "$SOFA_ARCHIVE_SHA256" \
  "$REMOTE_SOFA_INSTALL_ROOT" \
  "$REMOTE_SOFA_PYTHON_ENV" <<'REMOTE_SCRIPT'
set -euo pipefail
archive="$1"
expected_hash="$2"
install_root="$3"
python_env="$4"

actual_hash="$(sha256sum "$archive" | awk '{print $1}')"
printf 'remote_archive=%s\nremote_archive_sha256=%s\n' "$archive" "$actual_hash"
if [[ "$actual_hash" != "$expected_hash" ]]; then
  echo "Remote SOFA archive checksum mismatch." >&2
  exit 5
fi

mkdir -p "$install_root" "$(dirname "$python_env")"
if ! command -v unzip >/dev/null 2>&1; then
  echo "The system unzip command is required to preserve SOFA symlinks." >&2
  exit 6
fi
unzip -q -o "$archive" -d "$install_root"

runsofa="$(find "$install_root" -maxdepth 4 -path '*/bin/runSofa' -print -quit)"
if [[ -z "$runsofa" ]]; then
  echo "runSofa was not found after extraction." >&2
  exit 7
fi
sofa_root="$(dirname "$(dirname "$runsofa")")"
find "$sofa_root/bin" -maxdepth 1 -type f -exec chmod 755 {} +
printf '%s\n' "$sofa_root" >"$install_root/ACTIVE_ROOT"
export PATH="$sofa_root/bin:$PATH"
export LD_LIBRARY_PATH="$sofa_root/lib:$sofa_root/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

if [[ ! -x "$python_env/bin/python" ]]; then
  python3.10 -m venv --system-site-packages "$python_env"
fi
"$python_env/bin/python" -m pip install --upgrade pip
"$python_env/bin/python" -m pip install 'scipy>=1.8,<2' 'pybind11==2.12.0'

printf 'sofa_root=%s\nrunsofa=%s\npython_env=%s\n' \
  "$sofa_root" "$runsofa" "$python_env"
resolved_runsofa="$(readlink -f "$runsofa")"
printf 'runsofa_binary=%s\n' "$resolved_runsofa"
if ldd "$resolved_runsofa" | grep -q 'not found'; then
  echo "runSofa has unresolved shared-library dependencies." >&2
  ldd "$resolved_runsofa" >&2
  exit 8
fi
help_output="$(timeout 30 "$runsofa" -h 2>&1)"
printf '%s\n' "$help_output" | sed -n '1,8p'
"$python_env/bin/python" - <<'PY'
import json
import numpy
import pybind11
import scipy

print(json.dumps({
    "numpy": numpy.__version__,
    "scipy": scipy.__version__,
    "pybind11": pybind11.__version__,
}, indent=2))
PY
REMOTE_SCRIPT

echo "SOFA installation completed at $REMOTE_HOST:$REMOTE_SOFA_INSTALL_ROOT"
