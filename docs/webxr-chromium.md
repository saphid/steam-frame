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
90 GB of disk. It shallow-fetches the CL ref, runs `gclient sync --no-history`,
installs the sysroot, builds `chrome` with `symbol_level=0` and proprietary
codecs, and packs `chromium-xr-arm64.tar.xz`. Progress is logged to
`~/chromium-xr/stage`. The build aborts if `/` drops below 12 GB free.

First run: buildhost (12 cores, 31 GB RAM), started 2026-09-25.

## Running it on the Frame

[`scripts/chromium-xr.sh`](../scripts/chromium-xr.sh):

```sh
scripts/chromium-xr.sh install          # scp from buildhost, unpack to ~/chromium-xr
scripts/chromium-xr.sh launch [URL]     # headset desktop, --enable-features=OpenXR
scripts/chromium-xr.sh check            # prints isSessionSupported('immersive-vr')
```

It runs natively, not as a Flatpak, so the XR sandbox and SteamVR's IPC work
as the CL expects. It uses its own profile (`~/.config/chromium-xr`) and
DevTools on loopback port 9223, so it doesn't collide with the Flatpak's 9222.

**Verified 2026-09-25:**

- Vulkan is there: Turnip (Mesa) on Adreno 750, API 1.4.359.
- Unprivileged user namespaces work (`unshare -Ur true`), so Chromium's
  namespace sandbox shouldn't need the setuid `chrome_sandbox`.

**Unverified (inferred):**

- Chromium's GPU process may still fall back from Vulkan to GL on Turnip.
- An immersive session started from a window on the nested desktop may not
  hand over cleanly to the SteamVR compositor.
- If the sandbox fails to start, `--no-sandbox` is the fallback for a first
  test.
