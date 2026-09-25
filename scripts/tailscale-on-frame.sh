#!/usr/bin/env zsh
# Mac-side: install Tailscale on the Frame in userspace mode, so the `frame` SSH
# alias (and Frame Control) work from anywhere, not just the home LAN.
#
# Everything lives in the steamos user's home, so it needs no sudo and survives
# SteamOS updates:
#   ~/.local/share/tailscale/<version>/   static binaries (checksum-verified)
#   ~/.local/share/tailscale/state/       node key and state
#   ~/.local/bin/tailscale                CLI wrapper that finds the daemon's socket
#   ~/.config/systemd/user/tailscaled.service
# `tailscaled --tun=userspace-networking` needs no /dev/net/tun or root.
#
# Usage: scripts/tailscale-on-frame.sh [--version X.Y.Z] [--hostname NAME]
#        scripts/tailscale-on-frame.sh --uninstall
# The first run prints a login URL (and opens it on the Mac) to add the Frame
# to your tailnet. Env: FRAME_ALIAS (default frame).
set -euo pipefail

FRAME=${FRAME_ALIAS:-frame}
version="" hostname="frame" uninstall=0
while (( $# )); do
  case "$1" in
    --version) version=$2; shift ;;
    --hostname) hostname=$2; shift ;;
    --uninstall) uninstall=1 ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) print -u2 "unknown argument: $1"; exit 2 ;;
  esac
  shift
done
[[ $hostname =~ '^[A-Za-z0-9-]+$' ]] || { print -u2 "bad hostname: $hostname"; exit 2; }

if (( uninstall )); then
  ssh "$FRAME" 'set -e
    systemctl --user disable --now tailscaled.service 2>/dev/null || true
    rm -f ~/.config/systemd/user/tailscaled.service ~/.local/bin/tailscale ~/.local/bin/tailscaled
    systemctl --user daemon-reload
    echo "Removed the service and wrappers. Binaries and node state are still in ~/.local/share/tailscale;"
    echo "delete that folder and remove the machine in the Tailscale admin console to finish."'
  exit 0
fi

if [[ -z $version ]]; then
  version=$(curl -fsS "https://pkgs.tailscale.com/stable/?mode=json" |
            python3 -c 'import json,sys; print(json.load(sys.stdin)["TarballsVersion"])')
fi
[[ $version =~ '^[0-9]+\.[0-9]+\.[0-9]+$' ]] || { print -u2 "bad version: $version"; exit 2; }
print "==> Installing Tailscale $version on $FRAME (userspace networking)"

ssh "$FRAME" "VERSION=$version HOSTNAME_TS=$hostname sh -s" <<'REMOTE'
set -eu
base="$HOME/.local/share/tailscale"
dir="$base/$VERSION"
tgz="tailscale_${VERSION}_arm64.tgz"
mkdir -p "$base/state" "$HOME/.local/bin" "$HOME/.config/systemd/user"

if [ ! -x "$dir/tailscaled" ]; then
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL -o "$tmp/$tgz" "https://pkgs.tailscale.com/stable/$tgz"
  want=$(curl -fsSL "https://pkgs.tailscale.com/stable/$tgz.sha256" | cut -d' ' -f1)
  got=$(sha256sum "$tmp/$tgz" | cut -d' ' -f1)
  [ "$want" = "$got" ] || { echo "checksum mismatch for $tgz" >&2; exit 1; }
  tar -xzf "$tmp/$tgz" -C "$tmp"
  mkdir -p "$dir"
  mv "$tmp/tailscale_${VERSION}_arm64/tailscale" "$tmp/tailscale_${VERSION}_arm64/tailscaled" "$dir/"
fi
ln -sfn "$dir" "$base/current"

# The CLI looks for the daemon at /var/run/tailscale by default; point it at ours.
cat > "$HOME/.local/bin/tailscale" <<'EOF'
#!/bin/sh
exec "$HOME/.local/share/tailscale/current/tailscale" --socket="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/tailscale/tailscaled.sock" "$@"
EOF
chmod +x "$HOME/.local/bin/tailscale"

cat > "$HOME/.config/systemd/user/tailscaled.service" <<'EOF'
[Unit]
Description=Tailscale (userspace networking, no root)
After=network-online.target

[Service]
RuntimeDirectory=tailscale
ExecStart=%h/.local/share/tailscale/current/tailscaled --tun=userspace-networking --statedir=%h/.local/share/tailscale/state --socket=%t/tailscale/tailscaled.sock --port=41641
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable tailscaled.service >/dev/null 2>&1
systemctl --user restart tailscaled.service
for i in $(seq 1 50); do
  [ -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/tailscale/tailscaled.sock" ] && break
  sleep 0.2
done
"$HOME/.local/bin/tailscale" version | head -n 1
REMOTE

# `up` blocks until the login is approved, so run it in the background on the
# Frame and fetch the URL from its log.
state=$(ssh "$FRAME" '~/.local/bin/tailscale status --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)[\"BackendState\"])" 2>/dev/null || echo Unknown')
if [[ $state != Running ]]; then
  ssh "$FRAME" "nohup ~/.local/bin/tailscale up --hostname=$hostname --timeout=10m > /tmp/tailscale-up.log 2>&1 &"
  url=""
  for i in {1..40}; do
    url=$(ssh "$FRAME" 'grep -Eo "https://login\.tailscale\.com/[A-Za-z0-9/_-]+" /tmp/tailscale-up.log | head -n 1' || true)
    [[ -n $url ]] && break
    sleep 0.5
  done
  if [[ -n $url ]]; then
    print "==> Approve the Frame in your tailnet: $url"
    open "$url" 2>/dev/null || true
    print "    Waiting for approval (up to 10 minutes)…"
    for i in {1..300}; do
      state=$(ssh "$FRAME" '~/.local/bin/tailscale status --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)[\"BackendState\"])"' || true)
      [[ $state == Running ]] && break
      sleep 2
    done
  else
    print -u2 "No login URL yet; see /tmp/tailscale-up.log on the Frame."
  fi
fi

ssh "$FRAME" '~/.local/bin/tailscale status --self --peers=false; printf "Tailscale IP: "; ~/.local/bin/tailscale ip -4'
