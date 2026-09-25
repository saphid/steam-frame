# Open questions and on-device checks

Research as of 2026-09-25, eight days after the Frame's retail release
(2026-09-18). Most first-party detail comes from Valve's Steamworks developer
pages. Searches of Reddit and the Steam forums turned up **almost no
end-user reports** about SSH, desktop streaming, or macOS. Treat that as
"not documented yet", not "doesn't work".

## Check on the headset (in order)

1. **Is Developer Mode available on a retail unit?** Valve's pages are aimed at
   developers. Confirm that **Steam Settings → System → Enable Developer Mode**
   and **Developer → Set User Password** both exist on your OS channel (Stable
   vs Beta).
2. **Does SSH work straight after that, with no terminal steps?** From the Mac,
   run `nc -z frame.local 22`, then `./scripts/connect.sh`.
3. **Does `frame.local` resolve from the Mac (mDNS/Avahi)?** If not, use the IP
   and set up a DHCP reservation.
4. **Does SSH stay enabled after a reboot and after an OS update?** Also check
   that `~/.ssh/authorized_keys` survives an update.
5. **Is the `sshd_config.d` include present?** Check before `--harden`:
   `ssh frame 'grep -n Include /etc/ssh/sshd_config'`.
6. **What does Steam Link on macOS show when connected to `frame`?** Is it the
   VR view, a flat mirror, or the desktop? Does keyboard/mouse input reach the
   headset?
7. **Does the xrdp session work from Microsoft Windows App on macOS?** Valve
   only documents Windows Remote Desktop Connection. Is clipboard sync
   supported?
8. **What kind of session is the in-headset Linux desktop?** It could be a
   normal Plasma Wayland session (with a `wayland-*` socket in
   `/run/user/$(id -u)`), X11, or something nested in SteamVR. This decides
   whether `paste-to-frame.sh` works. `ssh frame 'ls /run/user/$(id -u); loginctl list-sessions'`.
9. **Are `wl-copy`, `xclip`, and `rsync` present on the image?**
   `ssh frame 'command -v wl-copy xclip rsync flatpak'`.
10. **Can Flatpaks be installed `--user` over SSH, and do they appear in the
    headset's desktop?** Test with `./scripts/install-apps.sh remmina`.
11. **Remmina → macOS Screen Sharing:** does it connect, and is it usable at
    Retina resolutions? Is the pre-seeded profile path
    (`~/.var/app/org.remmina.Remmina/data/remmina/`) the one Remmina
    actually reads?
12. **Moonlight Flatpak (aarch64) + Sunshine on macOS:** worth trying only if
    VNC is too slow.
13. **KDE Connect**: is it preinstalled or installable on the Frame, and does
    it pair with KDE Connect for macOS?
14. **Bluetooth keyboard pairing** on the Frame, for the rare times you do need
    to type locally.
15. **ADB**: does `adb shell` over USB-C from a Mac (not just a Windows PC)
    reach the Linux side? Does USB power from the Mac cope?
16. **Tailscale**: can it be installed persistently (Flatpak? a
    userspace `tailscaled` in `~`?) for access off the home LAN?

## Unconfirmed claims made in these docs

- `frame.local` works. This comes from one secondary search summary, with no
  primary source found.
- `/home` and `/etc` persist across Frame OS updates. This is inferred from
  Steam Deck behaviour.
- The whole Mac → Frame desktop path (VNC → Remmina). Each part is documented
  separately, but the combination is untested.
- Steam Remote Play with a Mac as host is broken. That's based on community
  reports, not tested with the Frame.
- None of the `scripts/` have run against real hardware. They were only
  syntax-checked on the Mac (see the commit message).
