#!/usr/bin/env zsh
# Mac-side: install APKs on the Frame.
#
# Default: each APK becomes its own app, in its own persistent Lepton
# instance with a Steam library shortcut (ui/frame_android.py). Nothing is
# lost when it closes.
#
# --dev: the old way, ADB into Lepton Development over an SSH tunnel. Apps
# installed like this are deleted when Lepton Development exits.
#
# Verified on a Frame 2026-09-25 (--split untested).
#
# Usage:
#   scripts/install-apk.sh APP.apk [APP2.apk ...]          # own instance each
#   scripts/install-apk.sh --dev APP.apk [APP2.apk ...]    # into Lepton Development
#   scripts/install-apk.sh --dev --split BASE.apk SPLIT.apk ...
#
# Env: FRAME_ALIAS (default frame), LOCAL_PORT (default: first free port from 15555).
set -euo pipefail

FRAME_ALIAS=${FRAME_ALIAS:-frame}
LEPTON_APPID=3056000
if [[ -z "${LOCAL_PORT:-}" ]]; then
  for LOCAL_PORT in {15555..15575}; do
    lsof -nP -iTCP:$LOCAL_PORT -sTCP:LISTEN >/dev/null 2>&1 || break
  done
fi
SERIAL="127.0.0.1:$LOCAL_PORT"
CTL="${TMPDIR:-/tmp}/frame-adb-$$.sock"

split=0
dev=0
apks=()
for arg in "$@"; do
  case "$arg" in
    --split) split=1 ;;
    --dev) dev=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) apks+=("$arg") ;;
  esac
done
(( ${#apks} )) || { sed -n '14,16p' "$0" >&2; exit 2; }
if (( ! dev )); then
  (( split )) && { print -u2 "--split needs --dev for now"; exit 2; }
  for apk in "${apks[@]}"; do
    print "==> Installing $apk as its own app"
    FRAME_ALIAS=$FRAME_ALIAS python3 "${0:A:h}/../ui/frame_android.py" install "$apk"
  done
  exit 0
fi
command -v adb >/dev/null || { print -u2 "adb missing: brew install android-platform-tools"; exit 1; }

for apk in "${apks[@]}"; do
  [[ -f "$apk" ]] || { print -u2 "not a file: $apk"; exit 1; }
  # The Frame is ARM64: native code must include lib/arm64-v8a/.
  libs=$(unzip -Z1 "$apk" 2>/dev/null | grep -E '^lib/[^/]+/' | cut -d/ -f2 | sort -u || true)
  if [[ -n "$libs" && "$libs" != *arm64-v8a* ]]; then
    print -u2 "!! $apk has native code for ${(j:, :)${(f)libs}} only; the Frame needs arm64-v8a"
    exit 1
  fi
done

lepton_listening() { ssh "$FRAME_ALIAS" 'ss -ltn | grep -q ":5555 "'; }

if ! lepton_listening; then
  print "==> Starting Lepton Development on the Frame"
  ssh "$FRAME_ALIAS" "steam steam://rungameid/$LEPTON_APPID >/dev/null 2>&1"
  for i in {1..30}; do
    lepton_listening && break
    (( i == 30 )) && { print -u2 "Lepton didn't open port 5555 within 60s. Is Lepton Development installed?"; exit 1; }
    sleep 2
  done
fi

print "==> Tunnelling ADB over SSH (localhost:$LOCAL_PORT -> $FRAME_ALIAS:5555)"
ssh -f -N -M -S "$CTL" -o ExitOnForwardFailure=yes \
  -L "127.0.0.1:$LOCAL_PORT:127.0.0.1:5555" "$FRAME_ALIAS"
cleanup() {
  adb disconnect "$SERIAL" >/dev/null 2>&1 || true
  ssh -S "$CTL" -O exit "$FRAME_ALIAS" >/dev/null 2>&1 || true
}
trap cleanup EXIT

adb connect "$SERIAL" | grep -q "connected to" || { print -u2 "adb connect $SERIAL failed"; exit 1; }
# A freshly started Lepton accepts ADB before Android has finished booting.
for i in {1..45}; do
  [[ "$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null)" == 1 ]] && break
  (( i == 45 )) && { print -u2 "Android in Lepton didn't finish booting within 90s"; exit 1; }
  sleep 2
done

if (( split )); then
  print "==> Installing split APK set (${#apks} files)"
  adb -s "$SERIAL" install-multiple -r "${apks[@]}"
else
  for apk in "${apks[@]}"; do
    print "==> Installing $apk"
    adb -s "$SERIAL" install -r "$apk"
  done
fi
