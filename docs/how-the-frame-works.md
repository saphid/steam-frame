# How the Frame is put together (field notes)

What we learnt by poking at a real Frame over SSH. Unless a line says
otherwise, it was **verified 2026-09-25** on SteamOS 0.3.0 (`VARIANT_ID=vr`,
build 20260922.6101926, kernel 6.18, aarch64). Topic docs go deeper. This page
is the map.

## The layer cake

```
SteamVR  (vrserver, vrcompositor, vrdashboard)       ← renders the room + panels
 └─ gamescope --backend openvr                       ← one SteamVR overlay per app id
     ├─ Xwayland :0  (Steam UI, games, tagged apps)  ← STEAM_GAME property = app id
     ├─ Xwayland :1  (STEAM_GAME_DISPLAY_0)
     ├─ Wayland socket gamescope-0
     └─ steamos-nested-desktop                       ← "the Linux desktop" panel
         └─ dbus-run-session startplasma-wayland
             └─ kwin_wayland 1280×800, Wayland wayland-0, Xwayland :2
                 └─ plasmashell, Konsole, Dolphin, Flatpaks you open there
Lepton (Android 11, podman container "lepton-dev") ← its own panel, app 3056000
```

## Facts worth knowing

| Fact | Where it matters |
|---|---|
| The desktop is a **nested** Plasma session: runtime dir `/run/user/1000/nested_plasma`, its own D-Bus bus, `WAYLAND_DISPLAY=wayland-0`, `DISPLAY=:2`. A plain `ssh frame app` can't find it. Copy the env from `plasmashell`'s `/proc/<pid>/environ`. | `run-on-frame.sh`, `paste-to-frame.sh` |
| The desktop size is hard-coded to 1280×800 in `/usr/bin/steamos-nested-desktop` (read-only rootfs). | [panels.md](panels.md) |
| gamescope runs with `--virtual-connector-strategy PerAppId`. Each app id becomes a SteamVR overlay `valve.steam.desktopgame.<id>`, which is a panel you can float. Setting `STEAM_GAME` on an X11 window on `:0` makes a new panel. | `panel-on-frame.sh`, [panels.md](panels.md) |
| Handy gamescope root properties on `:0`: `GAMESCOPE_FOCUSABLE_APPS`, `GAMESCOPE_FOCUSABLE_WINDOWS` (triples: window, app id, pid), `GAMESCOPE_FOCUSED_APP`. Read them with `DISPLAY=:0 xprop -root`. | Debugging panels |
| `gamescopectl screenshot <file>` (with `WAYLAND_DISPLAY=gamescope-0`) captures gamescope's flat layer. | Frame Control's capture |
| The **headset view** (both eyes, fully composited: room, panels, dashboard, controllers) comes from OpenVR `IVRScreenshots::RequestScreenshot(VRScreenshotType_Stereo)`. It's callable from `python3` with `ctypes` against `/opt/steamvr/bin/linuxarm64/libopenvr_api.so` as an overlay app. The compositor appends `.png`, writing a 1920×1080 side-by-side image (960×1080 per eye) plus a left-eye preview, in about 0.3s. In standby the frame is blank. `vrcmd --screenshot` and `vrcmd --compositorcmd screenshot_request` wrote nothing, even with `steamvr/rawCapturePath` set. | `ui/frame_vrshot.py` |
| Battery: `/sys/class/power_supply/max1720x_bat_7-36` gives µV/µA (current is positive while charging), `time_to_full_now`/`time_to_empty_now` in seconds, and `temp` in tenths of °C. The charger shows up as `tcpm-source-psy-…` (`type=USB`, `usb_type=C PD [PD_PPS]`), for example 12 V × 1.67 A. | Frame Control's battery card |
| `vrcmd --stats` reports `activity_level` (3 = standby). | Telling whether the headset is being worn |
| The SteamVR dashboard has docking: Float in World, Move, Size, Curvature, controller docking, Theater, Multitasking View. **Inferred** from `/opt/steamvr/resources/webinterface/dashboard/` and not yet driven by hand. | [panels.md](panels.md) |
| SteamVR settings live in `~/.config/openvr/config/steamvr.vrsettings`, not under `~/.local/share/Steam/config/`. `dashboard.lastAccessedExternalOverlayKey` names the last panel you used. | Settings tweaks |
| The Steam client's journal (`journalctl --user`) carries SteamVR system UI lines such as `[Overlays] Created: …` and `vroverlay_uid<appid>`. It's the quickest way to see panels come and go. | Debugging |
| Present: `rsync`, `flatpak`, `python3`, `git`, `qdbus6`, `xrdp`, `xprop`, `xwininfo`, `xterm`, `konsole`, `dolphin`, `gamescopectl`. Missing: `wl-copy`, `xclip`, `xsel`, `kdeconnect-cli`, `tailscale`, `krfb`, `wayvnc`. | Script design |
| Flathub is a **system** remote. `--user` installs over SSH work and show up in the desktop menu. | `install-apps.sh` |
| `/` is 10 GB and read-only. `/home` is 929 GB. | Where to put things |
| Clipboard: Klipper over the nested D-Bus bus (`qdbus6 org.kde.klipper …`). | `paste-to-frame.sh` |
| Lepton listens for ADB on the Frame's loopback `5555`, so tunnel it over SSH. It's Android 11 (API 30), 64-bit ARM only, with no `clipboard` service: Compose < 1.11, SDL/Kivy and Godot 4.3 apps crash on launch. | [apks.md](apks.md), `apk-catalog/` |
| Lepton Development deletes every ADB-installed app when it exits (`clear_baked_app_data "non steamlaunch container"` in `…/common/Lepton/lepton`) unless `LEPTON_NO_CLEANUP` is set. | [apks.md](apks.md) |
| Any APK can run as its own Lepton instance: run `…/common/Lepton/lepton waitforexitandrun -- app.apk` with `SteamAppId` set and `STEAM_COMPAT_DATA_PATH` under `~/.local/share/Steam`. Data persists and each gets its own container and panel. `frame/android/lepton-app.sh`, `ui/frame_android.py`. | [apks.md](apks.md) |
| The Steam client runs with `-cef-enable-debugging`, so its UI answers Chrome DevTools on loopback `127.0.0.1:8080`. The `SharedJSContext` page has `appStore` (owned apps), `downloadsStore` and `SteamClient.*`. `steam steam://install/<appid>` over SSH installs an owned game; when the options dialog shows (state 7), `SteamClient.Installs.ContinueInstall()` accepts it. **Verified 2026-09-25** with Balatro and Broforce. The Frame rating is `steam_hw_compat_category_packed >> 8 & 3`. | [steam-games.md](steam-games.md), `ui/frame_steam.py` |
| Chromium Flatpak 154 has **no immersive WebXR**: `navigator.xr` exists, but `isSessionSupported("immersive-vr")` returns `false`. Web VR180 players (DL8/DeoVR embeds) still play video inline as a flat, pannable view, and their VR button opens a tab on immersiveweb.dev. Forcing it doesn't help. `--enable-features=OpenXR,WebXR --force-webxr-runtime=openxr`, with `/opt/steamvr` and `XR_RUNTIME_JSON` exposed to the Flatpak, still returns `false`. The aarch64 Linux binary has no OpenXR code at all (no `xrCreateInstance`, no loader), even though `chrome://flags` lists `#webxr-runtime` → OpenXR. To watch in 3D, use a native player. Started with `--remote-debugging-port=9222`, Chromium answers DevTools on loopback. **Verified 2026-09-25**, BUILD_ID 20260922.6101926. | Web video, [panels.md](panels.md) |
| Power actions need `sudo`, which asks for the Developer Mode password over SSH. | Frame Control's power buttons |

## Debug recipes

```sh
# Which panels (app ids) exist right now?
ssh frame 'DISPLAY=:0 xprop -root GAMESCOPE_FOCUSABLE_APPS GAMESCOPE_FOCUSED_APP'

# Watch panels being created
ssh frame 'journalctl --user -f | grep --line-buffered "\[Overlays\]"'

# gamescope's full flags (in case Valve changes them)
ssh frame 'tr "\0" " " < /proc/$(pgrep -x gamescope | head -n 1)/cmdline'

# Everything the SteamVR dashboard can say (find hidden features)
ssh frame 'cat /opt/steamvr/resources/webinterface/dashboard/localization/dashboard_english.json'
```

## Where the rest lives

- Access and SSH: [ssh.md](ssh.md)
- Seeing the Frame from the Mac, and the Mac from the Frame: [streaming.md](streaming.md)
- Files and clipboard: [file-transfer.md](file-transfer.md)
- Android apps: [apks.md](apks.md)
- Installing and buying Steam games: [steam-games.md](steam-games.md)
- Floating windows in space: [panels.md](panels.md)
- What's still unverified: [open-questions.md](open-questions.md)
