#!/usr/bin/env zsh
# Mac-side (fallback only): serve bootstrap-on-frame.sh over plain HTTP on the
# LAN, with this Mac's Frame public key embedded, and print the short
# one-liner to type in Konsole on the headset. Ctrl-C to stop.
#
# UNTESTED against real hardware. Serves only a public key; use on a trusted LAN.
set -euo pipefail

PORT=${PORT:-8765}
here=${0:A:h}
KEY="$HOME/.ssh/id_ed25519_frame"

if [[ ! -f "$KEY.pub" ]]; then
  mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
  ssh-keygen -q -t ed25519 -N '' -C "mac->steam-frame" -f "$KEY"
fi
pub=$(<"$KEY.pub")

dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
# index.html so the bare URL works; curl doesn't care about the name.
sed "s|__PUBKEY__|$pub|" "$here/bootstrap-on-frame.sh" > "$dir/index.html"

name="$(scutil --get LocalHostName 2>/dev/null || hostname -s).local"
ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)

print "Type ONE of these in Konsole on the Frame:"
print "  curl -fsS $name:$PORT|bash"
[[ -n "$ip" ]] && print "  curl -fsS $ip:$PORT|bash"
print "Serving from $dir on port $PORT (Ctrl-C to stop)..."
python3 -m http.server "$PORT" --directory "$dir"
