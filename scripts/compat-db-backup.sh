#!/usr/bin/env zsh
# Mac-side: back up Frame Control's compatibility database (the private
# Lakebed capsule at https://frame-compat.lakebed.app).
#
# Exports every report through the app's own key (ui/frame_compat_db.py), keeps
# dated copies in ~/Library/Application Support/Frame Control/compat-db/backups (newest
# 60), and uploads to the Google Drive folder DRIVE_FOLDER_ID when the data
# changed since the last upload. Maintainer-only: it needs the database key.
# Run it daily from a LaunchAgent (see compat-db/README.md).
#
# Usage: scripts/compat-db-backup.sh [--no-upload] [--force-upload] [--accept-shrink]
# Env:   DRIVE_FOLDER_ID, GOG_WRAPPER
set -euo pipefail

ROOT="${0:A:h}/.."
DEST="$HOME/Library/Application Support/Frame Control/compat-db/backups"
DRIVE_FOLDER_ID=${DRIVE_FOLDER_ID:-}
GOG_WRAPPER=${GOG_WRAPPER:-$(command -v gog || true)}
upload=1 force=0 accept_shrink=0
for arg in "$@"; do
  case "$arg" in
    --no-upload) upload=0 ;;
    --force-upload) force=1 ;;
    --accept-shrink) accept_shrink=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) print -u2 "unknown option $arg"; exit 2 ;;
  esac
done

mkdir -p "$DEST"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out="$DEST/frame-compat-$stamp.json"
python3 "$ROOT/ui/frame_compat_db.py" export "$out"

# A backup that lost data is worse than none: refuse to shrink. Compare with the
# last backup that passed this check (.last-good), never with a refused one, so a
# loss keeps failing every day until someone looks and passes --accept-shrink.
count=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["count"])' "$out")
good="$DEST/.last-good"
if [[ -f "$good" ]]; then
  read -r good_count good_file < "$good"
  if (( count < good_count )) && (( ! accept_shrink )); then
    mv "$out" "$DEST/refused-${out:t}"
    print -u2 "!! export has $count reports; the last good backup ($good_file) had $good_count."
    print -u2 "!! Not uploading. Kept it as refused-${out:t}. If the loss is expected, rerun with --accept-shrink."
    exit 1
  fi
fi
print -r -- "$count ${out:t}" > "$good"

# Only the reports decide whether anything changed (not the export timestamp).
digest=$(python3 -c 'import json,sys,hashlib; r=json.load(open(sys.argv[1]))["reports"]; print(hashlib.sha256(json.dumps(sorted(r, key=lambda x: x["id"]), sort_keys=True).encode()).hexdigest())' "$out")
shasum -a 256 "$out" > "$out.sha256"
ls -1t "$DEST"/frame-compat-*.json | tail -n +61 | while read -r old; do rm -f "$old" "$old.sha256"; done
print "==> $count reports backed up to $out"

if (( upload )); then
  last="$DEST/.last-uploaded-digest"
  if (( ! force )) && [[ -f "$last" && "$(cat "$last")" == "$digest" ]]; then
    print "==> Unchanged since the last Drive upload; skipped"
    exit 0
  fi
  [[ -n "$DRIVE_FOLDER_ID" ]] || { print -u2 "Set DRIVE_FOLDER_ID, or pass --no-upload"; exit 1; }
  [[ -n "$GOG_WRAPPER" && -x "$GOG_WRAPPER" ]] || { print -u2 "gog not found; install it or set GOG_WRAPPER"; exit 1; }
  "$GOG_WRAPPER" drive upload "$out" --parent "$DRIVE_FOLDER_ID" --json --no-input >/dev/null
  "$GOG_WRAPPER" drive upload "$out.sha256" --parent "$DRIVE_FOLDER_ID" --json --no-input >/dev/null
  print -r -- "$digest" > "$last"
  print "==> Uploaded to Google Drive"
fi
