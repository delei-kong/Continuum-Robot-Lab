#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

PLUGIN_COMMIT="b6ce2bdf9257a9740c234489c013b82f9d7d5513"
PLUGIN_ARCHIVE="SofaValidation-${PLUGIN_COMMIT}.tar.gz"
PLUGIN_ARCHIVE_SHA256="9c62b93022d2957e45f05a801fe19c9287f916abdc5200e894a7dfe9f4e906e5"
PLUGIN_SOURCE_URL="https://codeload.github.com/sofa-framework/SofaValidation/tar.gz/${PLUGIN_COMMIT}"
LOCAL_ARCHIVE="${1:-$REMOTE_STATE_DIR/cache/$PLUGIN_ARCHIVE}"
REMOTE_DOWNLOAD_DIR="$REMOTE_RUNTIME_ROOT/downloads"
REMOTE_ARCHIVE="$REMOTE_DOWNLOAD_DIR/$PLUGIN_ARCHIVE"
REMOTE_PLUGIN_ROOT="$REMOTE_RUNTIME_ROOT/plugins/SofaValidation"
REMOTE_PLUGIN_INSTALL="$REMOTE_PLUGIN_ROOT/${PLUGIN_COMMIT}-sofa-${REMOTE_SOFA_VERSION}"

if [[ ! -f "$LOCAL_ARCHIVE" ]]; then
  if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to download the pinned SofaValidation source archive." >&2
    exit 3
  fi
  mkdir -p "$(dirname "$LOCAL_ARCHIVE")"
  partial_archive="${LOCAL_ARCHIVE}.partial.$$"
  trap 'rm -f "$partial_archive"' EXIT INT TERM
  curl -L --fail --retry 2 --connect-timeout 15 --max-time 120 \
    -o "$partial_archive" "$PLUGIN_SOURCE_URL"
  mv "$partial_archive" "$LOCAL_ARCHIVE"
  trap - EXIT INT TERM
fi

local_hash="$(LC_ALL=C shasum -a 256 "$LOCAL_ARCHIVE" | awk '{print $1}')"
if [[ "$local_hash" != "$PLUGIN_ARCHIVE_SHA256" ]]; then
  echo "SofaValidation source archive checksum mismatch." >&2
  echo "expected=$PLUGIN_ARCHIVE_SHA256" >&2
  echo "actual=$local_hash" >&2
  exit 4
fi

printf 'plugin_commit=%s\nlocal_archive=%s\narchive_sha256=%s\n' \
  "$PLUGIN_COMMIT" "$LOCAL_ARCHIVE" "$local_hash"
remote_exec mkdir -p "$REMOTE_DOWNLOAD_DIR" "$REMOTE_PLUGIN_ROOT"
if remote_exec test -f "$REMOTE_ARCHIVE"; then
  remote_hash="$(remote_exec sha256sum "$REMOTE_ARCHIVE" | awk '{print $1}')"
else
  remote_hash="missing"
fi
if [[ "$remote_hash" == "$PLUGIN_ARCHIVE_SHA256" ]]; then
  echo "Reusing verified remote archive: $REMOTE_ARCHIVE"
else
  scp "${SCP_ARGS[@]}" "$LOCAL_ARCHIVE" "$REMOTE_HOST:$REMOTE_ARCHIVE"
fi

remote_exec bash -s -- \
  "$REMOTE_ARCHIVE" \
  "$PLUGIN_ARCHIVE_SHA256" \
  "$PLUGIN_COMMIT" \
  "$REMOTE_SOFA_VERSION" \
  "$REMOTE_SOFA_INSTALL_ROOT" \
  "$REMOTE_PLUGIN_ROOT" \
  "$REMOTE_PLUGIN_INSTALL" <<'REMOTE_SCRIPT'
set -euo pipefail
archive="$1"
expected_hash="$2"
plugin_commit="$3"
sofa_version="$4"
sofa_install_root="$5"
plugin_root="$6"
plugin_install="$7"

actual_hash="$(sha256sum "$archive" | awk '{print $1}')"
if [[ "$actual_hash" != "$expected_hash" ]]; then
  echo "Remote SofaValidation source archive checksum mismatch." >&2
  exit 5
fi

active_sofa_file="$sofa_install_root/ACTIVE_ROOT"
if [[ ! -f "$active_sofa_file" ]]; then
  echo "SOFA is not installed: missing $active_sofa_file" >&2
  exit 6
fi
sofa_root="$(cat "$active_sofa_file")"
runsofa="$sofa_root/bin/runSofa"
if [[ ! -x "$runsofa" ]]; then
  echo "runSofa is missing: $runsofa" >&2
  exit 7
fi

missing_packages=()
for package in libboost1.74-dev libeigen3-dev; do
  if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'ok installed'; then
    missing_packages+=("$package")
  fi
done
if (( ${#missing_packages[@]} > 0 )); then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends "${missing_packages[@]}"
fi

plugin_library="$plugin_install/lib/libSofaValidation.so"
if [[ -e "$plugin_install" && ! -f "$plugin_library" ]]; then
  echo "Refusing to overwrite an incomplete plugin installation: $plugin_install" >&2
  exit 8
fi

if [[ ! -f "$plugin_library" ]]; then
  build_root="$(mktemp -d /tmp/sofa-validation-build.XXXXXX)"
  staging_install="$plugin_root/.install-${plugin_commit}-$$"
  cleanup_build() {
    rm -rf -- "$build_root"
    if [[ -d "$staging_install" ]]; then
      rm -rf -- "$staging_install"
    fi
  }
  trap cleanup_build EXIT INT TERM
  mkdir -p "$build_root/source" "$staging_install"
  tar -xzf "$archive" -C "$build_root/source" --strip-components=1
  cmake -S "$build_root/source" -B "$build_root/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH="$sofa_root" \
    -DCMAKE_INSTALL_PREFIX="$staging_install" \
    -DSOFAVALIDATION_BUILD_TESTS=OFF \
    -DCMAKE_DISABLE_FIND_PACKAGE_SofaCUDA=TRUE
  cmake --build "$build_root/build" --parallel 2
  cmake --install "$build_root/build"
  if [[ ! -f "$staging_install/lib/libSofaValidation.so" ]]; then
    echo "SofaValidation library was not produced." >&2
    exit 9
  fi
  {
    printf 'plugin=SofaValidation\n'
    printf 'source_commit=%s\n' "$plugin_commit"
    printf 'source_archive_sha256=%s\n' "$expected_hash"
    printf 'sofa_version=%s\n' "$sofa_version"
    printf 'sofa_root=%s\n' "$sofa_root"
    printf 'installed_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"$staging_install/INSTALL_METADATA"
  mv "$staging_install" "$plugin_install"
  trap - EXIT INT TERM
  rm -rf -- "$build_root"
fi

export PATH="$sofa_root/bin:$PATH"
export LD_LIBRARY_PATH="$sofa_root/lib:$sofa_root/bin:$plugin_install/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if ldd "$plugin_library" | grep -q 'not found'; then
  echo "SofaValidation has unresolved shared-library dependencies." >&2
  ldd "$plugin_library" >&2
  exit 10
fi

test_log="$(mktemp /tmp/sofa-validation-test.XXXXXX.log)"
test_scene="$plugin_install/share/sofa/examples/SofaValidation/Monitor.scn"
set +e
timeout 30 "$runsofa" -g batch -a -n 2 -l "$plugin_library" "$test_scene" \
  >"$test_log" 2>&1
test_exit=$?
set -e
if [[ "$test_exit" -ne 0 ]] || grep -q '\[ERROR\]' "$test_log"; then
  echo "SofaValidation load test failed." >&2
  sed -n '1,160p' "$test_log" >&2
  rm -f "$test_log"
  exit 11
fi
rm -f "$test_log"

active_plugin_tmp="$plugin_root/.ACTIVE_ROOT.$$"
printf '%s\n' "$plugin_install" >"$active_plugin_tmp"
mv "$active_plugin_tmp" "$plugin_root/ACTIVE_ROOT"
printf 'plugin_install=%s\nplugin_library=%s\nload_test=passed\n' \
  "$plugin_install" "$plugin_library"
REMOTE_SCRIPT

echo "SofaValidation installation completed at $REMOTE_HOST:$REMOTE_PLUGIN_INSTALL"
