#!/usr/bin/env zsh
# Mac-side: put text on the Steam Frame desktop clipboard.
#
# Needs the headset's desktop (Plasma) to be running. Text only; very large
# pastes (over ~100 KB) exceed the argument limit, so use push.sh for those.
#
# Usage:
#   scripts/paste-to-frame.sh        # sends the Mac clipboard (pbpaste)
#   some-cmd | scripts/paste-to-frame.sh -
set -euo pipefail

FRAME_ALIAS=${FRAME_ALIAS:-frame}

# Runs on the Frame. Clipboard text arrives on stdin.
# Verified 2026-09-25 (SteamOS 0.3.0 vr, build 20260922): the headset desktop is
# a nested Plasma Wayland session inside gamescope with its own D-Bus bus, and
# wl-copy/xclip are not installed. Klipper (org.kde.klipper, served by
# plasmashell) is reachable with qdbus6, so we borrow plasmashell's bus address.
remote=$(cat <<'EOF'
set -u
text=$(cat; printf x); text=${text%x}
pid=$(pgrep -u "$(id -u)" -x plasmashell | head -n 1)
if [ -z "$pid" ]; then
  echo "plasmashell is not running: open the desktop in the headset first." >&2
  exit 2
fi
bus=$(tr '\0' '\n' < "/proc/$pid/environ" | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')
if DBUS_SESSION_BUS_ADDRESS=$bus qdbus6 org.kde.klipper /klipper \
     org.kde.klipper.klipper.setClipboardContents "$text" >/dev/null; then
  echo "copied via Klipper (${#text} chars)"
else
  echo "Klipper call failed (bus: ${bus:-none})" >&2
  exit 2
fi
EOF
)
b64=$(print -rn -- "$remote" | base64)

if [[ "${1:-}" == "-" ]]; then
  ssh "$FRAME_ALIAS" "bash -c \"\$(echo $b64 | base64 -d)\""
else
  pbpaste | ssh "$FRAME_ALIAS" "bash -c \"\$(echo $b64 | base64 -d)\""
fi
