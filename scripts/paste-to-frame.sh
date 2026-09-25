#!/usr/bin/env zsh
# Mac-side: put text on the Steam Frame desktop clipboard.
#
# UNTESTED against real hardware. Assumes the in-headset desktop is a Plasma
# session owned by the SSH user; prints diagnostics if that assumption fails.
#
# Usage:
#   scripts/paste-to-frame.sh        # sends the Mac clipboard (pbpaste)
#   some-cmd | scripts/paste-to-frame.sh -
set -euo pipefail

FRAME_ALIAS=${FRAME_ALIAS:-frame}

# Runs on the Frame. Clipboard text arrives on stdin. setsid keeps the
# clipboard-serving process alive after the SSH session closes.
remote=$(cat <<'EOF'
set -u
tmp=$(mktemp)
cat > "$tmp"
rt=/run/user/$(id -u)
sock=$(ls "$rt" 2>/dev/null | grep -E '^wayland-[0-9]+$' | head -n 1)
if [ -n "$sock" ] && command -v wl-copy >/dev/null 2>&1 \
   && XDG_RUNTIME_DIR=$rt WAYLAND_DISPLAY=$sock setsid wl-copy < "$tmp" >/dev/null 2>&1; then
  echo "copied via wl-copy ($sock)"
elif command -v xclip >/dev/null 2>&1 \
   && DISPLAY=:0 setsid xclip -selection clipboard -i < "$tmp" >/dev/null 2>&1; then
  echo "copied via xclip (DISPLAY=:0)"
else
  echo "clipboard copy failed; diagnostics:" >&2
  echo "  runtime dir: $(ls "$rt" 2>&1 | tr '\n' ' ')" >&2
  echo "  wl-copy: $(command -v wl-copy || echo missing)  xclip: $(command -v xclip || echo missing)" >&2
  loginctl list-sessions --no-legend 2>&1 | sed 's/^/  session: /' >&2
  rm -f "$tmp"; exit 2
fi
rm -f "$tmp"
EOF
)
b64=$(print -rn -- "$remote" | base64)

if [[ "${1:-}" == "-" ]]; then
  ssh "$FRAME_ALIAS" "bash -c \"\$(echo $b64 | base64 -d)\""
else
  pbpaste | ssh "$FRAME_ALIAS" "bash -c \"\$(echo $b64 | base64 -d)\""
fi
