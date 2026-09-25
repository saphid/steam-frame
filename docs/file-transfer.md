# File transfer and clipboard

The confidence labels are the same as in [ssh.md](ssh.md). Everything here
depends on SSH working through the `frame` alias from `scripts/connect.sh`.

## Options

| Option | Command | Confidence | Notes |
|---|---|---|---|
| **scp / rsync over SSH** | `./scripts/push.sh file-or-dir [dest]`, or `rsync -a --progress x frame:Downloads/` | **Inferred.** SSH is confirmed. Valve recommends WinSCP (SFTP) for Windows ([debugging](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging)), which means SFTP is enabled. | Recommended. The Mac ships `rsync` (newer macOS uses `openrsync`, which supports the flags used here). `rsync` must also exist on the Frame. It's in SteamOS on Deck; if it's missing on the Frame, `push.sh` falls back to `scp`. |
| SFTP GUI | Finder can't do SFTP. Use Cyberduck / Transmit / ForkLift with `sftp://steamos@frame.local` | Inferred | Good for browsing. |
| `adb push` | `adb push x /sdcard/Download/` (Lepton) | Confirmed that ADB exists ([adb_lepton](https://partner.steamgames.com/doc/steamhardware/steamframe/adb_lepton)) | Only reaches the Android container's storage. |
| SteamOS Devkit Client | "Title Upload" | Confirmed (Frame) ([loadgames](https://partner.steamgames.com/doc/steamhardware/steamframe/loadgames)) | For deploying apps and games, not general files. macOS support for the Devkit Client wasn't confirmed. |
| Syncthing | A Syncthing Flatpak on the Frame (`./scripts/install-apps.sh <flathub-app-id>`), app on the Mac | Guess (which Syncthing Flatpak, and whether it has an aarch64 build, not checked) | Good for an ongoing shared folder. |
| KDE Connect | KDE Connect on both | Guess | There's a macOS build of KDE Connect, but whether it's present or installable on the Frame wasn't confirmed. It would give you clipboard sync, file send, and remote input. Worth checking on-device. |
| microSD | Physical card | Confirmed that the slot exists ([Wikipedia](https://en.wikipedia.org/wiki/Steam_Frame)) | Offline fallback. |

## Clipboard

`scripts/paste-to-frame.sh` sends the Mac clipboard (or stdin) to the
headset's desktop clipboard. You can then paste in the headset with the
virtual keyboard's paste key or a right-click → Paste.

```sh
./scripts/paste-to-frame.sh                 # sends pbpaste
echo "https://example.com" | ./scripts/paste-to-frame.sh -
```

How it works (verified 2026-09-25). The headset's desktop is a Plasma Wayland
session nested inside gamescope, with its own runtime dir
(`/run/user/1000/nested_plasma`) and its own D-Bus bus. `wl-copy` and `xclip`
aren't installed. The script reads the bus address from `plasmashell`'s
environment and calls Klipper's `setClipboardContents` with `qdbus6`. The
desktop has to be running in the headset. It's text only, and pastes over about
100 KB hit the argument limit, so send big things with `push.sh`.

A simpler fallback: `ssh frame 'cat > ~/clip.txt'` < file, then open it in the
headset.
