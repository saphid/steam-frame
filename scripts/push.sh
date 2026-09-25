#!/usr/bin/env zsh
# Mac-side: copy a file or folder to the Steam Frame.
#
# Verified on a Frame 2026-09-25.
#
# Usage: scripts/push.sh SOURCE [REMOTE_DEST]   (default dest: ~/Downloads/)
set -euo pipefail

FRAME_ALIAS=${FRAME_ALIAS:-frame}
src=${1:?usage: push.sh SOURCE [REMOTE_DEST]}
dest=${2:-Downloads/}

if ssh "$FRAME_ALIAS" 'command -v rsync >/dev/null'; then
  rsync -a --progress "$src" "$FRAME_ALIAS:${(q)dest}"  # remote shell parses the path
else
  print -u2 "rsync not found on the Frame; falling back to scp"
  scp -r "$src" "$FRAME_ALIAS:$dest"  # modern scp uses SFTP: no remote shell parsing
fi
