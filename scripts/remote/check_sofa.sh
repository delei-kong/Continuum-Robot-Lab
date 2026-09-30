#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

remote_exec bash -s -- \
  "$REMOTE_SOFA_INSTALL_ROOT" \
  "$REMOTE_SOFA_PYTHON_ENV" \
  "$REMOTE_RUNTIME_ROOT/plugins/SofaValidation" \
  "$REMOTE_RUNTIME_ROOT/plugins/ContinuumRobotLabViz" <<'REMOTE_SCRIPT'
set -euo pipefail
install_root="$1"
python_env="$2"
validation_root="$3"
visualization_root="$4"
active_root_file="$install_root/ACTIVE_ROOT"

if [[ ! -f "$active_root_file" ]]; then
  echo "SOFA is not installed: missing $active_root_file" >&2
  exit 3
fi

sofa_root="$(cat "$active_root_file")"
runsofa="$sofa_root/bin/runSofa"
test -x "$runsofa"
test -x "$python_env/bin/python"
export PATH="$sofa_root/bin:$PATH"
export LD_LIBRARY_PATH="$sofa_root/lib:$sofa_root/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

printf 'sofa_root=%s\nrunsofa=%s\n' "$sofa_root" "$runsofa"
resolved_runsofa="$(readlink -f "$runsofa")"
printf 'runsofa_binary=%s\n' "$resolved_runsofa"
if ldd "$resolved_runsofa" | grep -q 'not found'; then
  echo "runSofa has unresolved shared-library dependencies." >&2
  ldd "$resolved_runsofa" >&2
  exit 4
fi
help_output="$(timeout 30 "$runsofa" -h 2>&1)"
printf '%s\n' "$help_output" | sed -n '1,8p'
printf '\nPLUGIN DIRECTORIES\n'
find "$sofa_root/plugins" -maxdepth 1 -mindepth 1 -type d \
  \( -name 'SofaPython3' -o -name 'SoftRobots' -o -name 'STLIB' \) \
  -printf '%f\n' | sort
printf '\nPYTHON PACKAGES\n'
"$python_env/bin/python" -c \
  'import numpy, scipy, pybind11; print(numpy.__version__, scipy.__version__, pybind11.__version__)'

printf '\nOPTIONAL EXTERNAL PLUGINS\n'
validation_active_file="$validation_root/ACTIVE_ROOT"
if [[ -f "$validation_active_file" ]]; then
  validation_install="$(cat "$validation_active_file")"
  validation_library="$validation_install/lib/libSofaValidation.so"
  test -f "$validation_library"
  export LD_LIBRARY_PATH="$validation_install/lib:$LD_LIBRARY_PATH"
  if ldd "$validation_library" | grep -q 'not found'; then
    echo "SofaValidation has unresolved shared-library dependencies." >&2
    ldd "$validation_library" >&2
    exit 5
  fi
  printf 'SofaValidation=%s\n' "$validation_library"
else
  printf 'SofaValidation=not-installed\n'
fi

visualization_active_file="$visualization_root/ACTIVE_ROOT"
if [[ -f "$visualization_active_file" ]]; then
  visualization_install="$(cat "$visualization_active_file")"
  visualization_library="$visualization_install/lib/libContinuumRobotLabViz.so"
  imgui_library_dir="$sofa_root/plugins/SofaImGui/lib"
  test -f "$visualization_library"
  export LD_LIBRARY_PATH="$imgui_library_dir:$visualization_install/lib:$LD_LIBRARY_PATH"
  if ldd "$visualization_library" | grep -q 'not found'; then
    echo "ContinuumRobotLabViz has unresolved shared-library dependencies." >&2
    ldd "$visualization_library" >&2
    exit 6
  fi
  printf 'ContinuumRobotLabViz=%s\n' "$visualization_library"
else
  printf 'ContinuumRobotLabViz=not-installed\n'
fi
REMOTE_SCRIPT
