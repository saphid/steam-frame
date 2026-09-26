#!/bin/bash
# Frame-side: start the WebXR Chromium build (~/chromium-xr). The Steam
# library shortcut "Chromium XR" runs this, and so does
# `scripts/chromium-xr.sh launch` (which adds a DevTools port). Extra
# arguments go to Chrome, so a URL opens that page.
#
# Lives in ~/Applications/ChromiumXR, outside ~/chromium-xr, so reinstalling
# the build doesn't delete it.
set -euo pipefail

CHROME="$HOME/chromium-xr/chrome"
[[ -x "$CHROME" ]] || { echo "launch.sh: no build at $CHROME (run chromium-xr.sh install)" >&2; exit 1; }

# Without --no-first-run and --password-store=basic, startup can stop at a
# first-run or keyring prompt.
# --disable-seccomp-filter-sandbox: under the XR seccomp policy, SteamVR's
# client reads /proc/self/status through the file broker, gets the broker's
# pid, and SteamVR binds the app to the wrong process, so xrCreateInstance
# fails. The namespace sandbox stays on, but seccomp is off for every
# process, so keep this profile for VR sites.
exec "$CHROME" \
  --user-data-dir="$HOME/.config/chromium-xr" \
  --enable-features=OpenXR \
  --ozone-platform=x11 \
  --no-first-run --no-default-browser-check --password-store=basic \
  --disable-seccomp-filter-sandbox \
  "$@"
