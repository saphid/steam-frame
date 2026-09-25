# Screen and desktop streaming

This covers two directions:

- **A. Frame → Mac**: see and control the headset from the Mac.
- **B. Mac → Frame**: use the Mac's desktop inside the headset.

The confidence labels are the same as in [ssh.md](ssh.md).

## A. See and control the Frame from the Mac

| Option | What you get | Confidence | Notes |
|---|---|---|---|
| **Steam Link (macOS app) → `frame`** | A remote view of the headset | **Confirmed (Frame)**: Valve says to "use Steam Link on iOS, Android, or desktop to view the headset remotely by connecting to 'frame'" ([debugging](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging)) | Steam Link for macOS exists ([Tom's Guide](https://www.tomsguide.com/news/macbook-gaming-just-got-a-killer-upgrade-with-steam-link-heres-how-it-looks)). It's the lowest-effort option. Whether you get the VR view or a flat mirror, and whether input works, is unverified. |
| **RDP to xrdp** | A separate Linux (Xorg) desktop session as `steamos` | **Confirmed (Frame)** for the server ([debugging](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging)); **Inferred** for the Mac client | On the Mac, use Microsoft **Windows App** (the old "Microsoft Remote Desktop") from the App Store. Add PC `frame.local` (or the IP), user `steamos`, and the Developer Mode password. Valve says Xorg is the default session. This is a *separate* X session, not a mirror of what's in the headset. It's good for running GUI apps and supports clipboard sync. |
| **ADB + scrcpy (Lepton only)** | A mirror of the Android container | **Guess** | `brew install scrcpy android-platform-tools`, then `adb connect frame.local:5555` while Lepton Development is running ([adb_lepton](https://partner.steamgames.com/doc/steamhardware/steamframe/adb_lepton)), then `scrcpy`. This only shows Android apps, not SteamOS. |
| VNC server on the Frame (krfb / wayvnc) | A mirror of the Plasma desktop | **Inferred (SteamOS)** | Deck users run krfb in Desktop Mode ([one.vg](https://one.vg/blog/remote-control-your-steam-deck)). On the Frame, the in-headset desktop is a virtual screen, and krfb isn't known to be preinstalled. RDP and Steam Link cover this case, so it's not recommended. |

**Recommendation for A:** start with Steam Link for macOS, because Valve
documents it. Use Windows App (RDP) when you want a proper Linux desktop on the
Mac with keyboard, mouse, and clipboard.

## B. Show the Mac's desktop inside the Frame

The Frame's streaming features are built around a **Windows PC running
SteamVR** plus the USB Wi-Fi 6E dongle. Even Linux hosts had VR-streaming
problems at launch
([Steam discussion](https://steamcommunity.com/app/4165890/discussions/0/528765047224280796/),
[gbl08ma](https://gbl08ma.com/posts/steam-frame-a-linux-machine-doesnt-support-linux/)).
**macOS isn't a supported SteamVR host**, so for the Mac we're only looking at
flat 2D desktop streaming into a window on the Frame's Linux desktop.

| Option | Setup | Confidence | Verdict |
|---|---|---|---|
| **macOS Screen Sharing (VNC) → Remmina on the Frame** | **Mac:** System Settings → General → Sharing → Screen Sharing on → (i) → enable "VNC viewers may control screen with password". **Frame:** `./scripts/install-apps.sh remmina` from the Mac, then open Remmina in the headset and connect to `vnc://<mac>.local` | **Inferred.** Remmina is on Flathub for **aarch64** with VNC and RDP ([Flathub](https://flathub.org/apps/org.remmina.Remmina)). The Frame desktop runs Flatpaks ([UploadVR](https://www.uploadvr.com/flatpaks-open-source-steam-frame/)). macOS VNC is built in. | **Recommended.** Nothing to install on the Mac, and it's easy to set up. Latency is fine for productivity but not for games. You'll type the Mac's hostname once in Remmina on the headset, then save the profile. To avoid even that, the script can pre-seed a Remmina profile over SSH (see below). |
| Sunshine (Mac) → Moonlight (Frame Flatpak) | `brew install` Sunshine on the Mac, then `./scripts/install-apps.sh moonlight` | Moonlight Flatpak supports **aarch64** ([Flathub](https://flathub.org/apps/com.moonlight_stream.Moonlight)). **Sunshine on macOS is poorly supported**: install problems on Apple Silicon/Sequoia, and no virtual gamepads ([LizardByte discussion #777](https://github.com/orgs/LizardByte/discussions/777)). | Try it if VNC is too laggy. Expect some friction. |
| Steam Remote Play with the Mac as host | Steam on the Mac, Steam Link/Remote Play on the Frame | macOS-hosted Remote Play is reported broken or flaky in 2024–2026 ([Steam discussion](https://steamcommunity.com/groups/homestream/discussions/1/574921459914429988/)) | Not recommended. It's only for games, if it works at all. |
| Immersed / Virtual Desktop | Vendor apps | Immersed has a Mac agent but no known Frame client. Virtual Desktop's developer said he'd "try" to port it ([NewsBreak](https://www.newsbreak.com/news/4892834783961-virtual-desktop-dev-says-he-ll-try-to-bring-the-app-to-steam-frame)). | Not available as of 2026-09-25. Check again later. |
| WiVRn / ALVR | VR streaming from a Linux or Windows PC | Irrelevant for a Mac host (no SteamVR/OpenXR runtime on macOS) | N/A |

### Pre-seeding the Remmina profile (no typing in the headset)

`scripts/install-apps.sh remmina --vnc-host <your-mac>.local` writes
`~/.var/app/org.remmina.Remmina/data/remmina/mac-screen-sharing.remmina` on the Frame over
SSH. The profile then appears in Remmina's list, and you just click it. You'll
still be asked for the VNC password in the headset the first time, unless you
choose to save it. Remmina stores passwords encrypted with a per-install key,
so the script doesn't try to write the password. (The Remmina file format is
standard; the Flatpak data path is inferred.)

## Input and text entry without the virtual keyboard

- **A Bluetooth keyboard and mouse** paired to the Frame is the obvious way to
  avoid the virtual keyboard. Road to VR says there are "only a few things
  you'd actually want to do" on the Linux desktop unless you connect a
  keyboard and mouse.
  (Pairing a BT keyboard on the Frame is inferred from SteamOS; not verified.)
- **Clipboard from the Mac**: `scripts/paste-to-frame.sh` (see
  [file-transfer.md](file-transfer.md#clipboard)).
- **RDP session**: Windows App syncs the clipboard with xrdp, but only inside
  that RDP session.
