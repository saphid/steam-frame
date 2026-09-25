#!/usr/bin/env zsh
# Mac-side: upload VR videos to the Steam Frame so DeoVR can play them in 3D.
#
# Files go to ~/Videos/VR on the Frame. The script links that folder into
# DeoVR's Proton prefix as C:\users\steamuser\Videos\VR, so DeoVR's file
# browser finds it under Videos. (It's also reachable as Z:\home\steamos\Videos\VR.)
# Uploads resume if interrupted.
#
# Name files so DeoVR picks the projection: include _180 or _360 (or _fisheye190,
# _mkx200, _rf52 ...) plus the stereo layout (_LR / _SBS side by side, _TB over-
# under), e.g. "beach_180_LR.mp4". You can also change it in DeoVR's player.
#
# Usage:
#   scripts/push-vr-video.sh FILE_OR_DIR...       # upload
#   scripts/push-vr-video.sh --launch FILE...     # upload, then start DeoVR
#   scripts/push-vr-video.sh --launch             # just start DeoVR
#   scripts/push-vr-video.sh --list               # what's on the Frame
set -euo pipefail

FRAME_ALIAS=${FRAME_ALIAS:-frame}
DEOVR_APPID=837380
REMOTE_DIR="Videos/VR"
PREFIX_VIDEOS=".local/share/Steam/steamapps/compatdata/$DEOVR_APPID/pfx/drive_c/users/steamuser/Videos"

launch=0 list=0
while (( $# )); do
  case "$1" in
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    --launch)  launch=1; shift ;;
    --list)    list=1; shift ;;
    --)        shift; break ;;
    -*)        print -u2 "push-vr-video: unknown option $1"; exit 2 ;;
    *)         break ;;
  esac
done
(( $# || launch || list )) || { sed -n '2,18p' "$0"; exit 2; }

for f in "$@"; do
  [[ -e "$f" ]] || { print -u2 "push-vr-video: no such file: $f"; exit 2; }
done

# Create the folder and link it into DeoVR's prefix (the prefix exists once
# DeoVR has run). Never replace a real directory that's already there.
ssh "$FRAME_ALIAS" "mkdir -p ~/$REMOTE_DIR
p=~/$PREFIX_VIDEOS
if [ -d \"\$p\" ] && [ ! -e \"\$p/VR\" ]; then ln -s ~/$REMOTE_DIR \"\$p/VR\"; fi
[ -d \"\$p\" ] || echo 'note: DeoVR has not run yet; use Z:\\home\\steamos\\Videos\\VR or run this again after starting it once' >&2"

if (( $# )); then
  rsync -a --partial --progress "$@" "$FRAME_ALIAS:$REMOTE_DIR/"
fi

if (( list )); then
  ssh "$FRAME_ALIAS" "cd ~/$REMOTE_DIR && ls -lhR"
fi

if (( launch )); then
  ssh "$FRAME_ALIAS" "steam steam://rungameid/$DEOVR_APPID >/dev/null 2>&1 &"
  print "DeoVR starting on the Frame. Open Local files / the file browser → Videos → VR."
fi
