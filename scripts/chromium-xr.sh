#!/usr/bin/env zsh
# Mac-side: install and launch the WebXR-enabled Chromium build on the Frame.
#
# Flathub Chromium can't enter immersive WebXR on Linux: upstream only wires
# the OpenXR device on Windows (see docs/webxr-chromium.md). This deploys an
# arm64 build with the Linux OpenXR CLs, made on a Linux host by
# scripts/build-chromium-xr.sh, into ~/chromium-xr on the Frame (not a
# Flatpak, so SteamVR's sockets and the XR sandbox work unmodified).
#
# Usage:
#   scripts/chromium-xr.sh install [TARBALL]  # default: scp from $BUILD_HOST
#   scripts/chromium-xr.sh launch [URL]       # opens as its own panel in the headset
#   scripts/chromium-xr.sh steam              # adds "Chromium XR" to the Steam library
#   scripts/chromium-xr.sh check              # isSessionSupported via DevTools
set -euo pipefail

FRAME_ALIAS=${FRAME_ALIAS:-frame}
BUILD_HOST=${BUILD_HOST:-}
BUILD_TARBALL=${BUILD_TARBALL:-chromium-xr/chromium-xr-arm64.tar.xz}
DEVTOOLS_PORT=${DEVTOOLS_PORT:-9223}
STEAM_NAME=${STEAM_NAME:-Chromium XR}
here=${0:A:h}
wrapper='~/Applications/ChromiumXR/launch.sh'

# frame/chromium-xr/launch.sh holds Chrome's flags; both launch paths run it.
push_wrapper() {
  # Write then rename, so a dropped connection can't leave a torn script.
  ssh "$FRAME_ALIAS" 'mkdir -p ~/Applications/ChromiumXR && cd ~/Applications/ChromiumXR && cat > launch.sh.new && chmod +x launch.sh.new && mv launch.sh.new launch.sh' \
    < "$here/../frame/chromium-xr/launch.sh"
}

case "${1:-}" in
  install)
    tarball=${2:-}
    if [[ -z "$tarball" ]]; then
      [[ -n "$BUILD_HOST" ]] || { print -u2 "Pass a tarball, or set BUILD_HOST to the build machine"; exit 2; }
      tmp=$(mktemp -d)
      trap 'rm -rf "$tmp"' EXIT
      tarball=$tmp/chromium-xr-arm64.tar.xz
      scp -q "$BUILD_HOST:$BUILD_TARBALL" "$tarball"
    fi
    ssh "$FRAME_ALIAS" 'rm -rf ~/chromium-xr.new && mkdir -p ~/chromium-xr.new'
    ssh "$FRAME_ALIAS" 'tar -xJf - -C ~/chromium-xr.new' < "$tarball"
    # Check the new build runs before replacing the old one.
    ssh "$FRAME_ALIAS" '~/chromium-xr.new/chrome --version && rm -rf ~/chromium-xr && mv ~/chromium-xr.new ~/chromium-xr'
    ;;
  launch)
    # Its own VR panel on gamescope's X display, so the Plasma desktop doesn't
    # need to be open. DevTools is only on for this path (for `check`).
    push_wrapper
    exec "$here/panel-on-frame.sh" --name chromium-xr -- "$wrapper" \
      --remote-debugging-port="$DEVTOOLS_PORT" \
      "${2:-https://immersive-web.github.io/webxr-samples/}"
    ;;
  steam)
    # A non-Steam shortcut, added through the Steam client's DevTools port
    # without restarting Steam (see docs/apks.md). Launching it from the
    # library gives Chromium its own panel like any game. Safe to rerun: it
    # refreshes the wrapper and only adds the shortcut if it's missing.
    ssh "$FRAME_ALIAS" 'test -x ~/chromium-xr/chrome' ||
      { print -u2 "No build in ~/chromium-xr on the Frame: run 'chromium-xr.sh install' first"; exit 1; }
    push_wrapper
    # The app id is kept next to the wrapper, so renaming the shortcut in the
    # library doesn't make a rerun add a second one.
    shortcuts=$here/../frame/android/steam_shortcuts.py
    home=$(ssh "$FRAME_ALIAS" 'printf %s "$HOME"')
    saved=$(ssh "$FRAME_ALIAS" 'cat ~/Applications/ChromiumXR/shortcut-appid 2>/dev/null || true')
    existing=$(ssh "$FRAME_ALIAS" python3 - list < "$shortcuts" |
      python3 -c 'import json,sys
apps = json.load(sys.stdin)
ids = [a["appid"] for a in apps if str(a["appid"]) == sys.argv[2]] or [a["appid"] for a in apps if a["name"] == sys.argv[1]]
print(ids[0] if ids else "")' "$STEAM_NAME" "$saved")
    if [[ -n "$existing" ]]; then
      print -r -- "The shortcut is already in the Steam library (app id $existing)"
    else
      icon=''
      for dir in /var/lib/flatpak '~/.local/share/flatpak'; do
        candidate=$dir/exports/share/icons/hicolor/256x256/apps/org.chromium.Chromium.png
        if ssh "$FRAME_ALIAS" "test -f $candidate"; then icon=${candidate/#\~/$home}; break; fi
      done
      existing=$(ssh "$FRAME_ALIAS" python3 - add ${(q)STEAM_NAME} ${(q)home}/Applications/ChromiumXR/launch.sh ${(q)home} ${(q)icon} < "$shortcuts")
      [[ "$existing" == <-> ]] || { print -u2 -r -- "Steam didn't return a shortcut app id: $existing"; exit 1; }
      print -r -- "Added $STEAM_NAME to the Steam library (shortcut app id $existing)"
    fi
    ssh "$FRAME_ALIAS" "printf '%s\n' $existing > ~/Applications/ChromiumXR/shortcut-appid"
    ;;
  check)
    # DevTools listens on the Frame's loopback only; evaluate there.
    ssh "$FRAME_ALIAS" python3 - "$DEVTOOLS_PORT" <<'EOF'
import json, sys, urllib.request, base64, os, socket, struct
port = int(sys.argv[1])
tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=10))
page = next((t for t in tabs if t["type"] == "page"), None)
if page is None:
    sys.exit("no open page: run 'chromium-xr.sh launch' first")
path = page["webSocketDebuggerUrl"].split(f":{port}", 1)[1]
s = socket.create_connection(("127.0.0.1", port), timeout=30)
key = base64.b64encode(os.urandom(16)).decode()
s.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
       f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
       "Sec-WebSocket-Version: 13\r\n\r\n".encode())
s.recv(4096)
msg = json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
    "expression": "navigator.xr ? navigator.xr.isSessionSupported('immersive-vr') : 'no navigator.xr'",
    "awaitPromise": True}}).encode()
mask = os.urandom(4)
hdr = bytes([0x81]) + (bytes([0x80 | len(msg)]) if len(msg) < 126
                       else bytes([0x80 | 126]) + struct.pack(">H", len(msg)))
s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(msg)))
buf = b""
reply = None
while reply is None:
    chunk = s.recv(65536)
    if not chunk:
        sys.exit("DevTools closed the connection")
    buf += chunk
    # Consume every complete frame already buffered before reading again.
    while len(buf) >= 2:
        n = buf[1] & 0x7F
        off = 2
        if n == 126:
            if len(buf) < 4:
                break
            n, off = struct.unpack(">H", buf[2:4])[0], 4
        elif n == 127:
            if len(buf) < 10:
                break
            n, off = struct.unpack(">Q", buf[2:10])[0], 10
        if len(buf) < off + n:
            break
        frame, buf = buf[off:off + n], buf[off + n:]
        msg = json.loads(frame)
        if msg.get("id") == 1:
            reply = msg
            break
print("immersive-vr supported:", reply["result"]["result"].get("value"))
EOF
    ;;
  *) sed -n '2,14p' "$0"; exit 2 ;;
esac
