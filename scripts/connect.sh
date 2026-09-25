#!/usr/bin/env zsh
# Mac-side: find the Steam Frame, create a key, add a `Host frame` alias to
# ~/.ssh/config, copy the key, and optionally disable SSH password logins.
#
# UNTESTED against real hardware. Idempotent: safe to re-run.
#
# Usage:
#   scripts/connect.sh [HOST_OR_IP]          # set up key + alias
#   scripts/connect.sh [HOST_OR_IP] --harden # also disable password auth
#
# Env: FRAME_USER (default steamos), FRAME_ALIAS (default frame).
set -euo pipefail

FRAME_USER=${FRAME_USER:-steamos}
FRAME_ALIAS=${FRAME_ALIAS:-frame}
KEY="$HOME/.ssh/id_ed25519_frame"
CONFIG="$HOME/.ssh/config"
BEGIN_MARK="# >>> steam-frame ($FRAME_ALIAS) >>>"
END_MARK="# <<< steam-frame ($FRAME_ALIAS) <<<"

harden=0
host_arg=""
for arg in "$@"; do
  case "$arg" in
    --harden) harden=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) host_arg="$arg" ;;
  esac
done

port_open() {
  # nc resolves through the system resolver (including mDNS for .local).
  nc -z -G 3 "$1" 22 >/dev/null 2>&1
}

pick_host() {
  local candidates=()
  [[ -n "$host_arg" ]] && candidates+=("$host_arg")
  candidates+=("$FRAME_ALIAS.local" "$FRAME_ALIAS")
  local h
  for h in "${candidates[@]}"; do
    if port_open "$h"; then
      print -r -- "$h"; return 0
    fi
    print -u2 "  - $h: not resolvable or port 22 closed"
  done
  return 1
}

print "==> Looking for the Steam Frame"
if ! HOST=$(pick_host); then
  print -u2 "Could not reach the Frame on port 22."
  print -u2 "Check: Developer Mode on + user password set; same Wi-Fi; no client isolation."
  print -u2 "Then re-run with the IP from Quick Settings: scripts/connect.sh 192.168.x.y"
  exit 1
fi
print "    found: $HOST"

print "==> SSH key"
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
if [[ ! -f "$KEY" ]]; then
  ssh-keygen -q -t ed25519 -N '' -C "mac->steam-frame" -f "$KEY"
  print "    created $KEY"
else
  print "    exists: $KEY"
fi

print "==> ~/.ssh/config alias '$FRAME_ALIAS' -> $HOST"
touch "$CONFIG" && chmod 600 "$CONFIG"
tmp=$(mktemp)
# Drop any previous managed block, then PREPEND a fresh one: ssh uses the first
# value it sees per option, so this block must precede any other "Host frame"
# or "Host *". The trailing "Host *" returns the rest of the file to global scope.
awk -v b="$BEGIN_MARK" -v e="$END_MARK" '
  $0==b {skip=1; next}
  $0==e {skip=0; next}
  !skip {print}
' "$CONFIG" > "$tmp"
{
  print -r -- "$BEGIN_MARK"
  print -r -- "Host $FRAME_ALIAS"
  print -r -- "  HostName $HOST"
  print -r -- "  User $FRAME_USER"
  print -r -- "  IdentityFile $KEY"
  print -r -- "  IdentitiesOnly yes"
  print -r -- "  ServerAliveInterval 30"
  print -r -- "Host *"
  print -r -- "$END_MARK"
  cat "$tmp"
} > "$CONFIG"
rm -f "$tmp"

print "==> Checking key login"
if ssh -o BatchMode=yes -o ConnectTimeout=5 "$FRAME_ALIAS" true 2>/dev/null; then
  print "    key login already works"
else
  print "    copying key (enter the Developer Mode password once)"
  ssh-copy-id -i "$KEY.pub" -o IdentitiesOnly=yes "$FRAME_USER@$HOST"
  ssh -o BatchMode=yes -o ConnectTimeout=5 "$FRAME_ALIAS" true \
    || { print -u2 "Key login still failing after ssh-copy-id."; exit 1; }
  print "    key login OK"
fi

if (( harden )); then
  print "==> Disabling SSH password auth (sudo password asked on the Frame)"
  # shellcheck disable=SC2016
  if ! ssh -t "$FRAME_ALIAS" '
    set -e
    grep -Eiq "^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf" /etc/ssh/sshd_config \
      || { echo "sshd_config has no sshd_config.d include; not hardening."; exit 1; }
    printf "PasswordAuthentication no\nKbdInteractiveAuthentication no\n" \
      | { sudo mkdir -p /etc/ssh/sshd_config.d; sudo tee /etc/ssh/sshd_config.d/01-frame-keys-only.conf >/dev/null; }
    sudo sshd -t
    sudo systemctl reload sshd
    echo "password auth disabled"
  '; then
    print -u2 "!! Hardening failed. If the drop-in was written, it will disable password SSH"
    print -u2 "!! on the next sshd restart. To undo it:"
    print -u2 "!!   ssh $FRAME_ALIAS 'sudo rm -f /etc/ssh/sshd_config.d/01-frame-keys-only.conf'"
    exit 1
  fi
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "$FRAME_ALIAS" true; then
    print "    key login still OK after hardening"
  else
    print -u2 "!! Key login FAILED after hardening. Password SSH is now off."
    print -u2 "!! Recover via RDP or 'adb shell' (USB-C), then run:"
    print -u2 "!!   sudo rm /etc/ssh/sshd_config.d/01-frame-keys-only.conf && sudo systemctl reload sshd"
    exit 1
  fi
fi

print "\nDone. Try: ssh $FRAME_ALIAS"
