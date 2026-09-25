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
# Exposure: in userspace mode tailscaled forwards inbound tailnet connections
# to the Frame's loopback, so EVERY port is reachable from the tailnet,
# including localhost-only ones (Steam's DevTools on 8080, SteamVR, ADB).
# `tailscale set --shields-up` blocks all inbound (SSH too). See docs/tailscale.md.
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
    --version) version=${2:?--version needs a value}; shift ;;
    --hostname) hostname=${2:?--hostname needs a value}; shift ;;
    --uninstall) uninstall=1 ;;
    -h|--help) sed -n "2,21p" "$0"; exit 0 ;;
    *) print -u2 "unknown argument: $1"; exit 2 ;;
  esac
  shift
done
[[ $hostname =~ '^[A-Za-z0-9-]+$' ]] || { print -u2 "bad hostname: $hostname"; exit 2; }

if (( uninstall )); then
  ssh "$FRAME" 'set -e
    systemctl --user disable --now tailscaled.service 2>/dev/null || true
    rm -f ~/.config/systemd/user/tailscaled.service ~/.local/bin/tailscale
    systemctl --user daemon-reload
    echo "Removed the service and the CLI wrapper. Binaries and node state are still in"
    echo "~/.local/share/tailscale; delete that folder and remove the machine in the"
    echo "Tailscale admin console to finish. Linger stays on (loginctl disable-linger to undo)."'
  exit 0
fi

# BackendState of the Frame's tailscaled (Running, NeedsLogin, Stopped, …), or
# Unreachable when the probe itself fails (SSH down, daemon restarting).
ts_state() {
  ssh -o ConnectTimeout=10 "$FRAME" '~/.local/bin/tailscale status --json 2>/dev/null |
    python3 -c "import json,sys; print(json.load(sys.stdin)[\"BackendState\"])"' 2>/dev/null || print Unreachable
}

if [[ -z $version ]]; then
  version=$(curl -fsS "https://pkgs.tailscale.com/stable/?mode=json" |
            python3 -c 'import json,sys; print(json.load(sys.stdin)["TarballsVersion"])')
fi
[[ $version =~ '^[0-9]+\.[0-9]+\.[0-9]+$' ]] || { print -u2 "bad version: $version"; exit 2; }
print "==> Installing Tailscale $version on $FRAME (userspace networking)"

remote_out=$(ssh "$FRAME" "VERSION=$version sh -s" <<'REMOTE'
set -eu
base="$HOME/.local/share/tailscale"
dir="$base/$VERSION"
tgz="tailscale_${VERSION}_arm64.tgz"
unit="$HOME/.config/systemd/user/tailscaled.service"
sock="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/tailscale/tailscaled.sock"
mkdir -p "$base/state" "$HOME/.local/bin" "$HOME/.config/systemd/user"

if [ ! -x "$dir/tailscaled" ]; then
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  curl -fsSL -o "$tmp/$tgz" "https://pkgs.tailscale.com/stable/$tgz"
  want=$(curl -fsSL "https://pkgs.tailscale.com/stable/$tgz.sha256" | cut -d' ' -f1)
  [ -n "$want" ] || { echo "couldn't fetch $tgz.sha256" >&2; exit 1; }
  got=$(sha256sum "$tmp/$tgz" | cut -d' ' -f1)
  [ "$want" = "$got" ] || { echo "checksum mismatch for $tgz" >&2; exit 1; }
  tar -xzf "$tmp/$tgz" -C "$tmp"
  mkdir -p "$dir"
  mv "$tmp/tailscale_${VERSION}_arm64/tailscale" "$tmp/tailscale_${VERSION}_arm64/tailscaled" "$dir/"
fi
# Neither exists on a first install; don't let that trip set -e.
before=$({ readlink "$base/current"; cat "$unit"; } 2>/dev/null || true)
ln -sfn "$dir" "$base/current"

# The CLI looks for the daemon at /var/run/tailscale by default; point it at ours.
cat > "$HOME/.local/bin/tailscale" <<'EOF'
#!/bin/sh
exec "$HOME/.local/share/tailscale/current/tailscale" --socket="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/tailscale/tailscaled.sock" "$@"
EOF
chmod +x "$HOME/.local/bin/tailscale"

cat > "$unit" <<'EOF'
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
# Linger starts user services at boot, before anyone logs in; polkit allows it without sudo.
loginctl enable-linger 2>/dev/null || echo "note: couldn't enable linger; tailscaled starts when the session does" >&2
systemctl --user daemon-reload
systemctl --user enable tailscaled.service >/dev/null 2>&1
after=$(readlink "$base/current"; cat "$unit")
restart=0
if systemctl --user is-active --quiet tailscaled.service; then
  [ "$before" = "$after" ] || restart=1
else
  systemctl --user start tailscaled.service
fi
for i in $(seq 1 50); do
  [ -S "$sock" ] && break
  sleep 0.2
done
[ -S "$sock" ] || { echo "tailscaled didn't open $sock; see: journalctl --user -u tailscaled" >&2; exit 1; }
v=$("$HOME/.local/bin/tailscale" version)
printf 'Tailscale %s\n' "$(printf '%s\n' "$v" | head -n 1)"
if [ "$restart" = 1 ]; then
  # This SSH session may itself run over Tailscale, so restart detached, after
  # it has ended; the Mac waits and reconnects.
  systemd-run --user --quiet --on-active=3 --timer-property=AccuracySec=100ms --unit=tailscaled-restart --collect \
    systemctl --user restart tailscaled.service >/dev/null
  echo "RESTART_SCHEDULED"
fi
REMOTE
)
print -r -- "${remote_out//RESTART_SCHEDULED/Restarting tailscaled for the new version or unit…}"

# Wait out a scheduled restart, then read a definite state.
[[ $remote_out == *RESTART_SCHEDULED* ]] && sleep 6
state=""
for i in {1..30}; do
  state=$(ts_state)
  [[ $state == (Running|NeedsLogin|NeedsMachineAuth|Stopped|NoState) ]] && break
  sleep 2
done

case $state in
  Running) ;;
  NeedsLogin|Stopped|NoState)
    # `up` blocks until the login is approved, so run it as its own transient
    # unit (it outlives this SSH session) and fetch the URL from its log.
    ssh "$FRAME" "rm -f /tmp/tailscale-up.log; systemd-run --user --quiet --collect --unit=tailscale-up-\$\$ \
      sh -c '~/.local/bin/tailscale up --hostname=$hostname --timeout=10m > /tmp/tailscale-up.log 2>&1' >/dev/null"
    url=""
    for i in {1..40}; do
      url=$(ssh "$FRAME" 'grep -Eo "https://login\.tailscale\.com/[A-Za-z0-9/_-]+" /tmp/tailscale-up.log 2>/dev/null | head -n 1' || true)
      [[ -n $url ]] && break
      sleep 0.5
    done
    [[ -n $url ]] || { print -u2 "No login URL after 20 s; see /tmp/tailscale-up.log on the Frame."; exit 1; }
    print "==> Approve the Frame in your tailnet: $url"
    open "$url" 2>/dev/null || true
    print "    Waiting for approval (up to 10 minutes)…"
    for i in {1..300}; do
      state=$(ts_state)
      [[ $state == Running ]] && break
      sleep 2
    done
    [[ $state == Running ]] || { print -u2 "Not approved yet (state: $state). Re-run to get a new URL."; exit 1; }
    ;;
  NeedsMachineAuth) print -u2 "Logged in; approve the device in the Tailscale admin console, then re-run."; exit 1 ;;
  *) print -u2 "Couldn't read tailscaled's state (last: $state). Check: ssh $FRAME 'journalctl --user -u tailscaled'"; exit 1 ;;
esac

ssh "$FRAME" '~/.local/bin/tailscale status --self --peers=false; printf "Tailscale IP: "; ~/.local/bin/tailscale ip -4'
name=$(ssh "$FRAME" '~/.local/bin/tailscale status --json' | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
print "==> To use the Frame from anywhere, point the alias at Tailscale:"
print "    ssh-keyscan -t ed25519 $name >> ~/.ssh/known_hosts   # after checking it matches"
print "    scripts/connect.sh $name"
