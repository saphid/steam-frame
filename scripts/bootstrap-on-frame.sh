#!/bin/bash
# Runs ON the Steam Frame (fallback path only; normally Developer Mode's
# toggle + "Set User Password" is enough and this is not needed).
# Served by scripts/serve-bootstrap.sh, which substitutes the public key.
#
# UNTESTED against real hardware. Idempotent.
set -eu

KEY='__PUBKEY__'

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
if grep -qxF "$KEY" "$HOME/.ssh/authorized_keys"; then
  echo "key already present"
else
  echo "$KEY" >> "$HOME/.ssh/authorized_keys"
  echo "key added"
fi

echo "Enabling sshd. If sudo asks for a password you never set, press Ctrl-C,"
echo "set one in Steam Settings > Developer > Set User Password (or run: passwd),"
echo "then re-run the same one-liner."
sudo systemctl enable --now sshd

echo
echo "sshd: $(systemctl is-active sshd)   user: $(id -un)   host: $(hostname)"
ip -4 -brief addr show scope global 2>/dev/null || true
echo "Now on the Mac: scripts/connect.sh"
