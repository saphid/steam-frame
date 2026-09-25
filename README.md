# Steam Frame ↔ Mac

This repo holds notes and Mac-side helpers for controlling a Valve Steam Frame
(standalone VR headset: SteamOS 3, Arch-based, arm64, Snapdragon 8 Gen 3) from
this Mac, with as little typing on the headset's virtual keyboard as possible.

Status: research written 2026-09-25, then checked against a real Frame the same
day (SteamOS 0.3.0, variant `vr`, build 20260922). `connect.sh`, `push.sh`,
`paste-to-frame.sh` and `install-apps.sh` work; the rest are still untested. See
[docs/open-questions.md](docs/open-questions.md#verified-on-device-2026-09-25).

## Minimum typing on the headset

Valve's own developer docs say SSH, ADB, and RDP are all turned on through a
**UI toggle**. You don't need a terminal, `passwd`, or `systemctl`. The only
thing you type on the headset is a password you choose.

On the Frame:

1. **Steam Settings → System → Enable Developer Mode** (a toggle, no typing).
2. Scroll down to the **Developer** section and click **Set User Password**.
   Type a password. **This is the only thing you type on the headset.** Pick
   something short, because you'll type it once more on the Mac and then
   never again.
3. (Optional, no typing) Note the IP address from **Quick Settings** or
   **Steam Settings → Internet**, in case `frame.local` doesn't resolve.
4. (Optional) Check **Steam Settings → System → Hostname**. Leaving it as
   `frame` means the scripts work without any extra setup.

On the Mac:

```sh
cd ~/projects/steam-frame
./scripts/connect.sh              # or: ./scripts/connect.sh 192.168.1.50
ssh frame                          # passwordless from now on
```

`connect.sh` does four things:

- finds the headset (`frame.local`, then `frame`, or the IP/host you pass in)
- creates a dedicated key (`~/.ssh/id_ed25519_frame`)
- adds a `Host frame` block to `~/.ssh/config`
- runs `ssh-copy-id`, which asks for the Developer Mode password once

Run `./scripts/connect.sh --harden` later if you want to turn off SSH password
logins.

Sources: [Valve: Setting up your Steam Frame for development](https://partner.steamgames.com/doc/steamhardware/steamframe/setup),
[Valve: Steam Frame Debugging](https://partner.steamgames.com/doc/steamhardware/steamframe/debugging)
(both **confirmed on Steam Frame**, Valve official).

**Fallback, only if the Developer Mode toggle doesn't give you SSH.** From the
Mac, run `./scripts/serve-bootstrap.sh`. It prints a one-liner of about 30
characters, like `curl -fsS mac.local:8765|bash`, to type into Konsole on the
Frame's Linux desktop. The script it serves installs your Mac's public key and
enables `sshd`. See [docs/ssh.md](docs/ssh.md#fallback-bootstrap-one-liner).

## Recommended options

| Goal | Recommended | Confidence |
|---|---|---|
| Shell on the Frame | `ssh frame` (user `steamos`) | Confirmed (Valve docs) |
| **See/control the Frame from the Mac** | **Steam Link for macOS → connect to `frame`** (Valve names this). Alternatives: RDP to `xrdp` with Microsoft *Windows App* for the Linux desktop, or `adb`/`scrcpy` for the Android (Lepton) layer only | Steam Link and xrdp confirmed on Frame; the Mac RDP client is inferred |
| **Show the Mac's desktop inside the Frame** | **macOS Screen Sharing (built-in VNC) → Remmina (Flatpak, aarch64) on the Frame's Linux desktop**, installed over SSH | Inferred: each piece is documented, but the combination hasn't been tested on a Frame |
| File transfer | `scp` / `rsync` over the `frame` alias (`scripts/push.sh`) | **Verified** (rsync is on the image) |
| Paste Mac clipboard into the headset | `scripts/paste-to-frame.sh` (`pbpaste` → `ssh` → Klipper over D-Bus), or the clipboard sync in an RDP session | **Verified** (script); RDP untested |

Details: [docs/ssh.md](docs/ssh.md), [docs/streaming.md](docs/streaming.md),
[docs/file-transfer.md](docs/file-transfer.md),
[docs/open-questions.md](docs/open-questions.md).

## Scripts

| Script | Runs on | Purpose |
|---|---|---|
| `scripts/connect.sh` | Mac | Discover, set up key and `~/.ssh/config`, copy key, optional `--harden` (**verified**; `--harden` untested) |
| `scripts/install-apps.sh` | Mac → Frame | Install Flatpaks (Remmina, Moonlight, …) on the Frame over SSH as `--user` (**verified** with Remmina) |
| `scripts/paste-to-frame.sh` | Mac → Frame | Send the Mac clipboard (or stdin) to the Frame clipboard (**verified**) |
| `scripts/install-apk.sh` | Mac → Frame | Install APKs into Lepton with ADB tunnelled over SSH; starts Lepton Development if needed (**verified**; see [docs/apks.md](docs/apks.md) for app compatibility) |
| `scripts/run-on-frame.sh` | Mac → Frame | Start an app on the headset desktop, e.g. `mac-screen` opens Remmina straight into the Mac (**verified**) |
| `scripts/push.sh` | Mac → Frame | `rsync` files to `~/Downloads` (or a given path) on the Frame (**verified**) |
| `scripts/serve-bootstrap.sh` | Mac | Fallback: serve `bootstrap-on-frame.sh` with your public key embedded |
| `scripts/bootstrap-on-frame.sh` | Frame | Fallback: install the key and enable `sshd` |

## Security notes

- With Developer Mode on, `sshd`, ADB (Wi-Fi, port 5555, while a Lepton
  session is running), and xrdp are all reachable on your LAN. Use trusted
  networks only. Turn Developer Mode off when you don't need it.
- `steamos` has `sudo`, protected by the same Developer Mode password. Once
  you've switched to key auth, a short password still protects `sudo` and
  RDP, so pick one that isn't trivially guessable.
- Don't port-forward 22, 3389, or 5555 from your router. For remote access,
  use Tailscale (Flatpak/package availability for the Frame hasn't been
  checked).
