#!/usr/bin/env zsh
# Mac-side: start a GUI app on the Steam Frame's in-headset desktop over SSH.
#
# The headset desktop is a nested Plasma session inside gamescope with its own
# runtime dir, Wayland socket, X display and D-Bus bus (verified 2026-09-25), so
# a plain `ssh frame some-app` can't find it. This copies those variables from
# plasmashell's environment, then starts the app detached so it outlives SSH.
#
# Usage:
#   scripts/run-on-frame.sh remmina              # Remmina main window
#   scripts/run-on-frame.sh mac-screen           # Remmina straight into the Mac profile
#   scripts/run-on-frame.sh org.example.App [ARGS...]  # any installed Flatpak
#   scripts/run-on-frame.sh -- COMMAND [ARGS...]       # any command on the Frame
#
# A leading "~/" in any argument is expanded on the Frame.
set -euo pipefail

FRAME_ALIAS=${FRAME_ALIAS:-frame}
REMMINA_PROFILE="~/.var/app/org.remmina.Remmina/data/remmina/mac-screen-sharing.remmina"

case "${1:-}" in
  ""|-h|--help) sed -n '2,15p' "$0"; exit 0 ;;
  remmina)      cmd=(flatpak run org.remmina.Remmina) ;;
  mac-screen)   cmd=(flatpak run org.remmina.Remmina -c "$REMMINA_PROFILE") ;;
  --)           shift; (( $# )) || { print -u2 "run-on-frame: missing command after --"; exit 2; }
                cmd=("$@") ;;
  *)
    if [[ "$1" =~ '^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+){2,}$' ]]; then
      cmd=(flatpak run "$@")
    else
      print -u2 "run-on-frame: unknown app '$1' (use a Flatpak app ID, or -- COMMAND)"
      exit 2
    fi ;;
esac

# Runs on the Frame with the command as "$@".
remote=$(cat <<'EOF'
set -u
pid=$(pgrep -u "$(id -u)" -x plasmashell | head -n 1)
if [ -z "$pid" ]; then
  echo "plasmashell is not running: open the desktop in the headset first." >&2
  exit 2
fi
while IFS= read -r -d '' kv; do
  case "$kv" in
    WAYLAND_DISPLAY=*|XDG_RUNTIME_DIR=*|DISPLAY=*|XAUTHORITY=*|DBUS_SESSION_BUS_ADDRESS=*|\
    XDG_DATA_DIRS=*|XDG_CURRENT_DESKTOP=*|XDG_SESSION_TYPE=*) export "$kv" ;;
  esac
done < "/proc/$pid/environ"
args=()
for a in "$@"; do
  case "$a" in "~/"*) a="$HOME/${a#\~/}" ;; esac
  args+=("$a")
done
log=$(mktemp /tmp/run-on-frame.XXXXXX)
setsid nohup "${args[@]}" > "$log" 2>&1 < /dev/null &
child=$!
sleep 3
if kill -0 "$child" 2>/dev/null; then
  echo "started: ${args[*]} (pid $child, log $log)"
elif wait "$child"; then
  # Single-instance apps (e.g. Remmina) hand off to the running copy and exit 0.
  echo "done: ${args[*]} (exited 0; single-instance apps hand off to the running copy)"
  rm -f "$log"
else
  rc=$?
  echo "failed: ${args[*]} (exit $rc). Log:" >&2
  tail -n 20 "$log" >&2
  exit 1
fi
EOF
)
b64=$(print -rn -- "$remote" | base64)

ssh "$FRAME_ALIAS" "bash -c \"\$(echo $b64 | base64 -d)\" run-on-frame ${(j: :)${(@q)cmd}}"
