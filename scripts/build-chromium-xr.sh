#!/bin/bash
# Linux-side (x64 host): cross-compile arm64 Chromium with the Linux OpenXR CLs
# (8441736 + 8132979, bug 506004811) so WebXR immersive-vr works on the Frame.
# Needs ~90 GB free, no sudo. Takes hours; run it detached on the build host:
#   scp scripts/build-chromium-xr.sh buildhost:chromium-xr/build.sh
#   ssh buildhost 'cd ~/chromium-xr && tmux new -d -s chromium-xr "./build.sh > build.log 2>&1"'
# Progress: ~/chromium-xr/stage. Output: ~/chromium-xr/chromium-xr-arm64.tar.xz,
# which scripts/chromium-xr.sh install copies to the Frame.
# Re-running resumes: existing checkout and out/XR are reused.
set -euo pipefail
W=~/chromium-xr
cd "$W"
stage(){ echo "$(date -Is) $*" | tee -a "$W/stage"; }
# Returns non-zero below 12 GB free; set -e turns that into an exit at top level.
guard(){ avail=$(df --output=avail -BG "$W" | tail -n 1 | tr -dc 0-9); if [ "$avail" -lt 12 ]; then stage "ABORT: only ${avail}G free for $W"; return 3; fi; }
[ -d depot_tools ] || git clone -q https://chromium.googlesource.com/chromium/tools/depot_tools.git
export PATH="$W/depot_tools:$PATH" DEPOT_TOOLS_UPDATE=1 DEPOT_TOOLS_METRICS=0
CL_REF=refs/changes/79/8132979/44
if [ ! -f .gclient ]; then
  cat > .gclient <<'G'
solutions = [{ "name": "src", "url": "https://chromium.googlesource.com/chromium/src.git",
  "managed": False, "custom_deps": {}, "custom_vars": { "checkout_nacl": False } }]
target_os = ["linux"]
target_cpu = ["arm64"]
G
fi
# Keyed on a real commit, so an interrupted first fetch is retried on re-run.
if ! git -C src rev-parse -q --verify HEAD >/dev/null 2>&1; then
  stage "clone src at $CL_REF"
  mkdir -p src
  [ -d src/.git ] || git -C src init -q
  git -C src remote get-url origin >/dev/null 2>&1 || git -C src remote add origin https://chromium.googlesource.com/chromium/src.git
  git -C src fetch -q --depth=1 origin "$CL_REF"
  git -C src checkout -q FETCH_HEAD
fi
guard
stage "src at $(git -C src log -1 --format='%h %s')"
stage "gclient sync"
gclient sync --nohooks --no-history -D --shallow --revision "src@$(git -C src rev-parse HEAD)" -j 8
guard
stage "runhooks"
gclient runhooks
src/build/linux/sysroot_scripts/install-sysroot.py --arch=arm64
guard
cd src
mkdir -p out/XR
cat > out/XR/args.gn <<'A'
target_os = "linux"
target_cpu = "arm64"
is_debug = false
is_official_build = false
is_component_build = false
dcheck_always_on = false
symbol_level = 0
blink_symbol_level = 0
v8_symbol_level = 0
proprietary_codecs = true
ffmpeg_branding = "Chrome"
use_remoteexec = false
use_siso = true
treat_warnings_as_errors = false
A
stage "gn gen"
gn gen out/XR
gn args out/XR --list=enable_openxr --short | tee -a "$W/stage"
stage "build"
( while sleep 600; do guard || { pkill -u "$(id -u)" -f "siso|ninja"; exit 3; }; done ) &
GUARD=$!
trap 'kill $GUARD 2>/dev/null || true' EXIT
autoninja -C out/XR chrome chrome_sandbox chrome_crashpad_handler
stage "package"
cd out/XR
files=(chrome chrome_sandbox chrome_crashpad_handler *.pak *.bin icudtl.dat locales)
# GPU libraries aren't produced by every config; pack the ones that exist.
for f in libEGL.so libGLESv2.so libvk_swiftshader.so libvulkan.so.1 vk_swiftshader_icd.json; do
  [ -e "$f" ] && files+=("$f")
done
tar -cJf "$W/chromium-xr-arm64.tar.xz" "${files[@]}"
stage "DONE $(ls -la $W/chromium-xr-arm64.tar.xz)"
