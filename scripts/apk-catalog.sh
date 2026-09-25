#!/usr/bin/env zsh
# Mac-side: refresh the Android app catalogue that Frame Control shows
# (apk-catalog/). Fetches the latest F-Droid index, scans new or updated APKs
# with HTTP range requests, and rebuilds apk-catalog/site/apps.js.
# Frame Control picks up the new data on its next page load.
#
# Usage: scripts/apk-catalog.sh   (the first full scan takes about an hour;
#                                  later runs only scan what changed)
set -euo pipefail

CAT="${0:A:h}/../apk-catalog"
[[ "${1:-}" == -h || "${1:-}" == --help ]] && { sed -n '2,8p' "$0"; exit 0; }

print "==> Fetching the F-Droid index"
curl -fL --progress-bar -o "$CAT/data/index-v2.json.part" https://f-droid.org/repo/index-v2.json
mv "$CAT/data/index-v2.json.part" "$CAT/data/index-v2.json"
print "==> Scanning new or updated APKs"
WORKERS=40 python3 "$CAT/scan.py"
WORKERS=40 python3 "$CAT/scan2.py"
print "==> Rebuilding"
python3 "$CAT/build.py"
