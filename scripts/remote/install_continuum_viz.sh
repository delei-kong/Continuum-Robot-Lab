#!/usr/bin/env bash

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

PLUGIN_VERSION="0.1.0"
PLUGIN_SOURCE_ROOT="$PROJECT_ROOT/src/visualization/sofa_imgui_control_plot"
REMOTE_PLUGIN_SOURCE_ROOT="$REMOTE_PROJECT_ROOT/src/visualization/sofa_imgui_control_plot"
REMOTE_PLUGIN_ROOT="$REMOTE_RUNTIME_ROOT/plugins/ContinuumRobotLabViz"

IMGUI_VERSION="1.91.8"
IMGUI_ARCHIVE="imgui-v${IMGUI_VERSION}.tar.gz"
IMGUI_SHA256="db3a2e02bfd6c269adf0968950573053d002f40bdfb9ef2e4a90bce804b0f286"
IMGUI_URL="https://codeload.github.com/ocornut/imgui/tar.gz/refs/tags/v${IMGUI_VERSION}"

IMPLOT_VERSION="0.16"
IMPLOT_ARCHIVE="implot-v${IMPLOT_VERSION}.tar.gz"
IMPLOT_SHA256="961df327d8a756304d1b0a67316eebdb1111d13d559f0d3415114ec0eb30abd1"
IMPLOT_URL="https://codeload.github.com/epezent/implot/tar.gz/refs/tags/v${IMPLOT_VERSION}"

SOURCE_FILES=(
  CMakeLists.txt
  src/ControlPlotGUI.cpp
  src/ControlPlotGUI.h
  src/init.cpp
)

if [[ ! -d "$PLUGIN_SOURCE_ROOT" ]]; then
  echo "Missing visualization plugin source: $PLUGIN_SOURCE_ROOT" >&2
  exit 3
fi

source_manifest="$(mktemp)"
cleanup_manifest() {
  rm -f "$source_manifest"
}
trap cleanup_manifest EXIT INT TERM
for relative_file in "${SOURCE_FILES[@]}"; do
  file_hash="$(LC_ALL=C shasum -a 256 "$PLUGIN_SOURCE_ROOT/$relative_file" | awk '{print $1}')"
  printf '%s  %s\n' "$file_hash" "$relative_file" >>"$source_manifest"
done
source_hash="$(LC_ALL=C shasum -a 256 "$source_manifest" | awk '{print $1}')"
source_hash_short="${source_hash:0:12}"
REMOTE_PLUGIN_INSTALL="$REMOTE_PLUGIN_ROOT/v${PLUGIN_VERSION}-${source_hash_short}-sofa-${REMOTE_SOFA_VERSION}"

download_and_verify() {
  local archive_path="$1"
  local source_url="$2"
  local expected_hash="$3"
  local partial_archive

  if [[ ! -f "$archive_path" ]]; then
    if ! command -v curl >/dev/null 2>&1; then
      echo "curl is required to download visualization build dependencies." >&2
      exit 4
    fi
    mkdir -p "$(dirname "$archive_path")"
    partial_archive="${archive_path}.partial.$$"
    if ! curl -L --fail --retry 2 --connect-timeout 15 --max-time 120 \
      -o "$partial_archive" "$source_url"; then
      rm -f "$partial_archive"
      return 1
    fi
    mv "$partial_archive" "$archive_path"
  fi

  actual_hash="$(LC_ALL=C shasum -a 256 "$archive_path" | awk '{print $1}')"
  if [[ "$actual_hash" != "$expected_hash" ]]; then
    echo "Dependency archive checksum mismatch: $archive_path" >&2
    echo "expected=$expected_hash" >&2
    echo "actual=$actual_hash" >&2
    exit 5
  fi
}

LOCAL_IMGUI_ARCHIVE="$REMOTE_STATE_DIR/cache/$IMGUI_ARCHIVE"
LOCAL_IMPLOT_ARCHIVE="$REMOTE_STATE_DIR/cache/$IMPLOT_ARCHIVE"
download_and_verify "$LOCAL_IMGUI_ARCHIVE" "$IMGUI_URL" "$IMGUI_SHA256"
download_and_verify "$LOCAL_IMPLOT_ARCHIVE" "$IMPLOT_URL" "$IMPLOT_SHA256"

REMOTE_DOWNLOAD_DIR="$REMOTE_RUNTIME_ROOT/downloads"
REMOTE_IMGUI_ARCHIVE="$REMOTE_DOWNLOAD_DIR/$IMGUI_ARCHIVE"
REMOTE_IMPLOT_ARCHIVE="$REMOTE_DOWNLOAD_DIR/$IMPLOT_ARCHIVE"
remote_exec mkdir -p "$REMOTE_DOWNLOAD_DIR" "$REMOTE_PLUGIN_ROOT"

copy_if_needed() {
  local local_archive="$1"
  local remote_archive="$2"
  local expected_hash="$3"
  local remote_hash="missing"
  if remote_exec test -f "$remote_archive"; then
    remote_hash="$(remote_exec sha256sum "$remote_archive" | awk '{print $1}')"
  fi
  if [[ "$remote_hash" == "$expected_hash" ]]; then
    echo "Reusing verified remote archive: $remote_archive"
  else
    scp "${SCP_ARGS[@]}" "$local_archive" "$REMOTE_HOST:$remote_archive"
  fi
}

copy_if_needed "$LOCAL_IMGUI_ARCHIVE" "$REMOTE_IMGUI_ARCHIVE" "$IMGUI_SHA256"
copy_if_needed "$LOCAL_IMPLOT_ARCHIVE" "$REMOTE_IMPLOT_ARCHIVE" "$IMPLOT_SHA256"

remote_exec bash -s -- \
  "$REMOTE_SOFA_INSTALL_ROOT" \
  "$REMOTE_PLUGIN_SOURCE_ROOT" \
  "$source_hash" \
  "$PLUGIN_VERSION" \
  "$REMOTE_IMGUI_ARCHIVE" \
  "$IMGUI_SHA256" \
  "$IMGUI_VERSION" \
  "$REMOTE_IMPLOT_ARCHIVE" \
  "$IMPLOT_SHA256" \
  "$IMPLOT_VERSION" \
  "$REMOTE_PLUGIN_ROOT" \
  "$REMOTE_PLUGIN_INSTALL" \
  "${SOURCE_FILES[@]}" <<'REMOTE_SCRIPT'
set -euo pipefail
sofa_install_root="$1"
source_root="$2"
expected_source_hash="$3"
plugin_version="$4"
imgui_archive="$5"
imgui_hash="$6"
imgui_version="$7"
implot_archive="$8"
implot_hash="$9"
implot_version="${10}"
plugin_root="${11}"
plugin_install="${12}"
shift 12
source_files=("$@")

if [[ ! -d "$source_root" ]]; then
  echo "Remote visualization source is missing; synchronize the workspace first." >&2
  exit 6
fi
remote_manifest="$(mktemp)"
cleanup_manifest() {
  rm -f "$remote_manifest"
}
trap cleanup_manifest EXIT INT TERM
for relative_file in "${source_files[@]}"; do
  file_hash="$(sha256sum "$source_root/$relative_file" | awk '{print $1}')"
  printf '%s  %s\n' "$file_hash" "$relative_file" >>"$remote_manifest"
done
actual_source_hash="$(sha256sum "$remote_manifest" | awk '{print $1}')"
if [[ "$actual_source_hash" != "$expected_source_hash" ]]; then
  echo "Remote visualization source differs from the local source." >&2
  exit 7
fi
if [[ "$(sha256sum "$imgui_archive" | awk '{print $1}')" != "$imgui_hash" ]] \
  || [[ "$(sha256sum "$implot_archive" | awk '{print $1}')" != "$implot_hash" ]]; then
  echo "Remote visualization dependency checksum mismatch." >&2
  exit 8
fi

active_sofa_file="$sofa_install_root/ACTIVE_ROOT"
if [[ ! -f "$active_sofa_file" ]]; then
  echo "SOFA is not installed: missing $active_sofa_file" >&2
  exit 9
fi
sofa_root="$(cat "$active_sofa_file")"
imgui_root="$sofa_root/plugins/SofaImGui"
imgui_library="$imgui_root/lib/libSofaImGui.so.25.12.00"
if [[ ! -f "$imgui_library" ]]; then
  echo "SofaImGui library is missing: $imgui_library" >&2
  exit 10
fi
if ! strings "$imgui_library" | grep -F "Dear ImGui $imgui_version" >/dev/null \
  || ! strings "$imgui_library" | grep -F "ImPlot $implot_version" >/dev/null; then
  echo "Installed SofaImGui does not match the pinned ImGui/ImPlot headers." >&2
  exit 11
fi

plugin_library="$plugin_install/lib/libContinuumRobotLabViz.so"
if [[ -e "$plugin_install" && ! -f "$plugin_library" ]]; then
  echo "Refusing to overwrite an incomplete plugin installation: $plugin_install" >&2
  exit 12
fi

if [[ ! -f "$plugin_library" ]]; then
  build_root="$(mktemp -d /tmp/continuum-viz-build.XXXXXX)"
  staging_install="$plugin_root/.install-$$"
  cleanup_build() {
    rm -rf -- "$build_root"
    if [[ -d "$staging_install" ]]; then
      rm -rf -- "$staging_install"
    fi
  }
  trap 'cleanup_manifest; cleanup_build' EXIT INT TERM
  mkdir -p "$build_root/imgui" "$build_root/implot" "$staging_install"
  tar -xzf "$imgui_archive" -C "$build_root/imgui" --strip-components=1
  tar -xzf "$implot_archive" -C "$build_root/implot" --strip-components=1
  cmake -S "$source_root" -B "$build_root/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH="$sofa_root" \
    -DCMAKE_INSTALL_PREFIX="$staging_install" \
    -DSOFA_IMGUI_ROOT="$imgui_root" \
    -DSOFA_IMGUI_LIBRARY="$imgui_library" \
    -DIMGUI_SOURCE_ROOT="$build_root/imgui" \
    -DIMPLOT_SOURCE_ROOT="$build_root/implot"
  cmake --build "$build_root/build" --parallel 2
  cmake --install "$build_root/build"
  if [[ ! -f "$staging_install/lib/libContinuumRobotLabViz.so" ]]; then
    echo "Visualization plugin library was not produced." >&2
    exit 13
  fi
  {
    printf 'plugin=ContinuumRobotLabViz\n'
    printf 'plugin_version=%s\n' "$plugin_version"
    printf 'source_sha256=%s\n' "$expected_source_hash"
    printf 'imgui_version=%s\n' "$imgui_version"
    printf 'imgui_archive_sha256=%s\n' "$imgui_hash"
    printf 'implot_version=%s\n' "$implot_version"
    printf 'implot_archive_sha256=%s\n' "$implot_hash"
    printf 'sofa_root=%s\n' "$sofa_root"
    printf 'installed_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"$staging_install/INSTALL_METADATA"
  mv "$staging_install" "$plugin_install"
  trap cleanup_manifest EXIT INT TERM
  rm -rf -- "$build_root"
fi

export LD_LIBRARY_PATH="$sofa_root/lib:$sofa_root/bin:$imgui_root/lib:$plugin_install/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if ldd "$plugin_library" | grep -q 'not found'; then
  echo "Visualization plugin has unresolved shared-library dependencies." >&2
  ldd "$plugin_library" >&2
  exit 14
fi

test_root="$(mktemp -d /tmp/continuum-viz-test.XXXXXX)"
test_scene="$test_root/empty.scn"
test_log="$test_root/stdout.log"
printf '%s\n' '<Node name="root" dt="0.01"></Node>' >"$test_scene"
set +e
timeout 30 "$sofa_root/bin/runSofa" -g batch -a -n 1 \
  -l SofaImGui -l "$plugin_library" "$test_scene" >"$test_log" 2>&1
test_exit=$?
set -e
if [[ "$test_exit" -ne 0 ]] || grep -q '\[ERROR\]' "$test_log" \
  || ! grep -q "Loaded plugin: $plugin_library" "$test_log"; then
  echo "Visualization plugin load test failed." >&2
  sed -n '1,180p' "$test_log" >&2
  rm -rf -- "$test_root"
  exit 15
fi
rm -rf -- "$test_root"

active_plugin_tmp="$plugin_root/.ACTIVE_ROOT.$$"
printf '%s\n' "$plugin_install" >"$active_plugin_tmp"
mv "$active_plugin_tmp" "$plugin_root/ACTIVE_ROOT"
printf 'plugin_install=%s\nplugin_library=%s\nload_test=passed\n' \
  "$plugin_install" "$plugin_library"
REMOTE_SCRIPT

echo "ContinuumRobotLabViz installation completed at $REMOTE_HOST:$REMOTE_PLUGIN_INSTALL"
