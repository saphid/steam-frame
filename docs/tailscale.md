# Tailscale: use the Frame from anywhere

With Tailscale on the Frame, the `frame` SSH alias works off the home LAN, and
so does everything built on it: Frame Control, the scripts and the Mac app.
When the Mac and the Frame are on the same network, Tailscale connects them
directly, so there's no relay in the way (`tailscale ping frame` → `via
192.168.1.50:41641`, 20 ms).

```sh
scripts/tailscale-on-frame.sh          # install or update, then approve the login URL
scripts/connect.sh frame.<tailnet>.ts.net   # point the alias at Tailscale (the script prints this)
scripts/tailscale-on-frame.sh --uninstall
```

## How it's installed

There's no Tailscale Flatpak, and the rootfs is read-only. So the script
installs Tailscale's static arm64 build in the `steamos` user's home and runs
`tailscaled --tun=userspace-networking` as a systemd **user** service. It
doesn't need sudo, and SteamOS updates don't touch it.

| Path | What |
|---|---|
| `~/.local/share/tailscale/<version>/` | `tailscale`, `tailscaled` (SHA-256 checked against pkgs.tailscale.com) |
| `~/.local/share/tailscale/current` | Symlink to the active version |
| `~/.local/share/tailscale/state/` | Node key and state |
| `~/.local/bin/tailscale` | CLI wrapper that points at the daemon's socket (`$XDG_RUNTIME_DIR/tailscale/tailscaled.sock`) |
| `~/.config/systemd/user/tailscaled.service` | The service |

Lingering (`loginctl enable-linger`) is on, so the service starts at boot
without anyone logging in. polkit allowed that without sudo. Re-running the
script is safe. It restarts `tailscaled` only if the version or unit changed,
and then does so detached after 3 s, because the SSH session may itself run
over Tailscale.

To update, run the script again; it installs the latest stable version. To
manage the node, use `ssh frame '~/.local/bin/tailscale status'` (or `set`,
`down`, `up`).

**Verified 2026-09-25 (SteamOS 0.3.0, build 20260922.6101926, Tailscale
1.102.4):**

- First install and login approval. This ran an earlier revision of the script,
  which restarted the daemon unconditionally. The node is `frame`,
  with a 100.x.y.z tailnet address.
- SSH works over Tailscale: the Frame serves the same ED25519 host key as it
  does on `frame.local`.
- Frame Control's status and Get games work through the alias.
- The current script: a re-run with nothing changed doesn't restart anything,
  and a re-run with a changed unit restarts `tailscaled` 3 s after the SSH
  session ends and then reads `Running`. The timer needs
  `AccuracySec=100ms`; the default of 1 min made it fire up to a minute late.
  The first-install guard was checked on its own.

**Not verified:**

- A clean first install and login with the current script end to end. It would
  mean removing the node from the tailnet.
- Reaching the Frame from outside the home network. Only the direct LAN path
  was tested.
- The service coming up after a reboot. That's **inferred** from linger plus
  `WantedBy=default.target`; the Frame hasn't been rebooted since.

## Exposure: every port is on the tailnet

In userspace mode, `tailscaled` passes inbound tailnet connections to the
Frame's **loopback**. Any device on the tailnet can therefore reach **every**
listening port, including ones meant to be local-only. Checked from the Mac on
2026-09-25:

| Port | Service | Normally |
|---|---|---|
| 22 | sshd | LAN |
| 8080 | Steam client DevTools (full control of the Steam client and account session) | loopback only |
| 27062 | SteamVR `vrserver` | loopback only |
| 5555 | Lepton ADB (unauthenticated shell into Android) | LAN |
| 3389 | xrdp | LAN |

The user accepted this on 2026-09-25, since the tailnet only holds their own
devices. Other options:

- `tailscale set --shields-up` blocks **all** inbound connections. That
  includes SSH and Tailscale SSH (`--ssh`), both checked.
- A tailnet policy that tags the Frame (`tag:frame`) and allows only
  `tag:frame:22` keeps the other ports private. This is an admin-console
  change.
- Kernel-mode Tailscale (a root install, e.g. systemd-sysext) wouldn't expose
  loopback-only ports, but it needs sudo and may not survive SteamOS updates.

If the Mac's Tailscale is off, the alias won't resolve. Use
`scripts/connect.sh frame.local` to go back to the LAN name.
