# WebXR in Chromium on the Frame

Goal: open a web VR180 or 360 player (DeoVR and DL8 embeds, WebXR samples),
press its VR button, and watch in 3D in the headset.

## Why Flathub Chromium can't

**Verified 2026-09-25** (Frame BUILD_ID 20260922.6101926, Flathub
`org.chromium.Chromium` 154.0.8037.57 aarch64):

- `navigator.xr` exists, but `isSessionSupported("immersive-vr")` is `false`.
  Flags don't change that, and neither does `--force-webxr-runtime=openxr`
  with SteamVR exposed to the Flatpak.
- The binary has no OpenXR loader: no `XR_RUNTIME_JSON`,
  `xrGetInstanceProcAddr` or `XR_LOADER_DEBUG` strings. The only OpenXR
  strings are the `chrome://flags` entries.

**Cause (verified against Chromium source, same date).** M154 is the first
release that compiles OpenXR on Linux:

- `device/vr/buildflags/buildflags.gni` adds `is_linux` to `enable_openxr`.
- Flathub's tarball sets `checkout_openxr = true`.
- Flathub's GN args don't turn it off.

But `content/services/isolated_xr_device/xr_runtime_provider.cc` only creates
the OpenXR device under `ENABLE_OPENXR && IS_WIN`. That's true on 154, 155 and
`main`. Nothing on Linux calls the OpenXR code, so the linker drops it. The
rest of the Linux port is in two unmerged CLs (bug 506004811):

- [8441736](https://chromium-review.googlesource.com/c/chromium/src/+/8441736)
  runs the XR device service in a Linux sandbox that allows SteamVR's
  sockets, `/dev/shm` and `flock`.
- [8132979](https://chromium-review.googlesource.com/c/chromium/src/+/8132979)
  wires the provider to `OpenXrPlatformHelperLinux`. `kOpenXR` stays off by
  default, so it needs `--enable-features=OpenXR`.

8132979 sits on top of 8441736, so fetching `refs/changes/79/8132979/<ps>`
gets both.

**The Frame side is ready.** `~/.config/openxr/1/active_runtime.json` names
SteamVR (`bin/linuxarm64/vrclient.so`, `VALVE_runtime_is_steamvr`). The
Linux backend uses Vulkan (`XR_USE_GRAPHICS_API_VULKAN`).

## Building it

[`scripts/build-chromium-xr.sh`](../scripts/build-chromium-xr.sh)
cross-compiles arm64 Linux Chromium on an x64 Linux host. It doesn't need
sudo: the arm64 sysroot comes from Chromium's own script. It needs about
90 GB of disk. It shallow-fetches the CL ref (patchset 44), runs
`gclient sync --no-history`, installs the sysroot, applies one extra seccomp
fix (below), builds `chrome` with `symbol_level=0` and proprietary codecs, and
packs `chromium-xr-arm64.tar.xz` (about 145 MB, GPU libraries included).
Progress is logged to `~/chromium-xr/stage`. The build aborts if the disk
holding `~/chromium-xr` drops below 12 GB free.

First run, 2026-09-25, on a 12-core, 31 GB x64 Linux box: 9 h 33 min for
94,835 steps, giving Chromium 156.0.8071.0. A rebuild after a one-file change
takes under a minute, plus about 4 minutes to repack.

**The extra fix.** The CL's XR seccomp policy refuses `getsockopt`. SteamVR's
client calls `getsockopt(SOL_SOCKET, SO_PEERCRED)` inside `xrCreateInstance`,
so the XR process died with a seccomp crash (arm64 syscall 209). The script
allows that one option. That's needed but not enough: `launch` still turns
seccomp off (below), so the patch only matters once that's fixed too.

## Running it on the Frame

[`scripts/chromium-xr.sh`](../scripts/chromium-xr.sh):

```sh
BUILD_HOST=my-linux-box scripts/chromium-xr.sh install  # your build host; scp, unpack to ~/chromium-xr
scripts/chromium-xr.sh launch [URL]     # its own VR panel, --enable-features=OpenXR
scripts/chromium-xr.sh check            # prints isSessionSupported('immersive-vr')
```

It runs natively, not as a Flatpak. `launch` opens it as its own panel on
gamescope's X display, the same way as [`panel-on-frame.sh`](../scripts/panel-on-frame.sh) ([panels.md](panels.md)), so
the Plasma desktop doesn't need to be open. It uses its own profile
(`~/.config/chromium-xr`) and DevTools on loopback port 9223, so it doesn't
collide with the Flatpak's 9222. When a page enters VR, Chrome asks
**Allow VR?** in the browser panel; choose *Allow this time* or *Allow while
visiting the site*.

**Seccomp is off.** `launch` passes `--disable-seccomp-filter-sandbox`. With
the XR seccomp policy on, SteamVR's client reads `/proc/self/status` through
Chrome's file broker and gets the broker's pid. SteamVR then binds the app to
the wrong process ("Unable to init path manager: VRInitError_Init_Internal")
and `xrCreateInstance` fails. The broker can't answer `/proc/self` for another
process, so fixing this needs a change in Chromium's broker client or in the
CL. The namespace sandbox stays on, but seccomp is off for every process, so
use this profile for VR sites rather than everyday browsing. DevTools on
port 9223 has no authentication. It listens on loopback, but with the
userspace Tailscale from [tailscale.md](tailscale.md) running, loopback ports
are reachable from your tailnet. Close the browser when you're done.

**Verified 2026-09-26** (Frame BUILD_ID 20260922.6101926, SteamVR 2.17.10,
this build):

- `isSessionSupported('immersive-vr')` is `true`. The WebXR samples page
  shows "VR support detected".
- `requestSession('immersive-vr')` succeeds after the prompt. With a WebGL
  layer, the first XR frame has a viewer pose with 2 views and a
  2880 × 1440 framebuffer (1440 × 1440 per eye).
- SteamVR moves the app from `VRApplication_OpenXRInstance` to
  `VRApplication_OpenXRScene` and gives it scene focus. `xrEndFrame` submits
  both projection views, and the compositor receives the 2880 × 1440 scene.
- The OpenXR runtime uses Vulkan (`XR_KHR_vulkan_enable2`). Chromium's own GPU
  process uses ANGLE on GL, running on zink over Turnip Vulkan (Adreno 750);
  Chromium's Vulkan backend is off. That doesn't stop the session.
- Unprivileged user namespaces work (`unshare -Ur true`), so the namespace
  sandbox runs without the setuid `chrome_sandbox`.

**Not verified yet:** nobody was wearing the headset during the test, so
SteamVR kept it in standby. The session stayed at
`XR_SESSION_STATE_SYNCHRONIZED` (the page saw `visibilityState: "hidden"`)
and only the first frame ran. Still open:

- Whether the image shows up correctly in the headset, and at what frame rate.
- Whether VR180 or 360 video players (DeoVR, DL8 embeds) play in 3D.
- Controller and hand input in the session.
