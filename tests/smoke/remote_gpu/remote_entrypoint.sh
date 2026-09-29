#!/usr/bin/env bash

set -u

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <python_executable> <run_dir>" >&2
  exit 2
fi

python_executable="$1"
run_dir="$2"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$run_dir"

set +e
"$python_executable" "$script_dir/train_sine.py" \
  --output-dir "$run_dir" \
  --steps 800 \
  --seed 20260927 \
  >"$run_dir/stdout.log" 2>&1
exit_code=$?
set -e

printf '%s\n' "$exit_code" >"$run_dir/exit_code"
if [[ "$exit_code" -eq 0 ]]; then
  touch "$run_dir/COMPLETE"
else
  touch "$run_dir/FAILED"
fi

exit "$exit_code"
