# Valve's devkit-utils (vendored)

Unmodified copy of `client/devkit-utils/` from Valve's
[SteamOS Devkit Client](https://gitlab.steamos.cloud/devkit/steamos-devkit),
MIT licensed (see `LICENSE`; Valve's own notes are in `VALVE-README.md`).

- Source: steamos-devkit, commit `6f0711a` ("Code drop."),
  release **v0.20260925.1** (ChangeLog entry dated 2026-09-25).

`ui/frame_titles.py` copies this folder to `~/devkit-utils` on the Frame (where
Valve's own client puts it) and uses `steamos-prepare-upload`,
`steam-client-create-shortcut`, `steam-devkit-rpc` and `steamos-delete` to
register uploaded builds as Steam "Devkit Games". See `docs/sideloading.md`.

To update: copy the folder from a newer checkout over this one, keep this
README, and update the version line above. The stamp Frame Control compares
on the headset is a hash of these files, so a changed copy is re-synced on the
next use.
