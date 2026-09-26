#!/bin/bash
# Linux-side (x64 host): cross-compile arm64 Chromium with the Linux OpenXR CLs
# (8441736 + 8132979, bug 506004811), plus a one-option seccomp fix, so WebXR
# immersive-vr works on the Frame.
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
# CL 8441736's XR seccomp policy refuses getsockopt, and SteamVR's IPC client
# calls getsockopt(SO_PEERCRED) inside xrCreateInstance, which crashes the XR
# process (verified on the Frame 2026-09-26). Allow only that option.
IFS= read -r -d '' PEERCRED_PATCH <<'P' || true
diff --git a/sandbox/policy/linux/bpf_xr_policy_linux.cc b/sandbox/policy/linux/bpf_xr_policy_linux.cc
index 435e13d396..297453f582 100644
--- a/sandbox/policy/linux/bpf_xr_policy_linux.cc
+++ b/sandbox/policy/linux/bpf_xr_policy_linux.cc
@@ -11,6 +11,7 @@
 #include "sandbox/linux/system_headers/linux_syscalls.h"
 #include "sandbox/policy/linux/sandbox_linux.h"
 
+using sandbox::bpf_dsl::AllOf;
 using sandbox::bpf_dsl::Allow;
 using sandbox::bpf_dsl::Arg;
 using sandbox::bpf_dsl::Error;
@@ -27,8 +28,8 @@ XrProcessPolicy::~XrProcessPolicy() = default;
 ResultExpr XrProcessPolicy::EvaluateSyscall(int system_call_number) const {
   switch (system_call_number) {
     // The runtime reaches its compositor over an AF_UNIX socket and passes fds
-    // with SCM_RIGHTS, neither of which the GPU policy allows. get/setsockopt
-    // stay disallowed; add a narrow level/optname restriction if ever needed.
+    // with SCM_RIGHTS, neither of which the GPU policy allows. setsockopt
+    // stays disallowed; getsockopt is limited to SO_PEERCRED below.
 #if defined(__NR_getpeername)
     case __NR_getpeername:
 #endif
@@ -49,6 +50,16 @@ ResultExpr XrProcessPolicy::EvaluateSyscall(int system_call_number) const {
     case __NR_get_robust_list:
 #endif
       return Allow();
+#if defined(__NR_getsockopt)
+    case __NR_getsockopt: {
+      // SteamVR's IPC client checks who is on the other end of its socket
+      // with SO_PEERCRED. Nothing else is readable.
+      const Arg<int> level(1);
+      const Arg<int> optname(2);
+      return If(AllOf(level == SOL_SOCKET, optname == SO_PEERCRED), Allow())
+          .Else(Error(EPERM));
+    }
+#endif
 #if defined(__NR_kill)
     case __NR_kill: {
       // SteamVR probes its sibling processes for liveness with kill(pid, 0).
P
if ! printf '%s\n' "$PEERCRED_PATCH" | git apply --reverse --check 2>/dev/null; then
  printf '%s\n' "$PEERCRED_PATCH" | git apply
  stage "applied SO_PEERCRED patch"
fi
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
