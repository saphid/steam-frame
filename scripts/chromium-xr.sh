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
#   scripts/chromium-xr.sh install [TARBALL]  # default: fetch from $BUILD_HOST
#   scripts/chromium-xr.sh launch [URL]       # opens in the headset desktop
#   scripts/chromium-xr.sh check              # isSessionSupported via DevTools
set -euo pipefail

FRAME_ALIAS=${FRAME_ALIAS:-frame}
BUILD_HOST=${BUILD_HOST:-buildhost}
BUILD_TARBALL=${BUILD_TARBALL:-chromium-xr/chromium-xr-arm64.tar.xz}
DEVTOOLS_PORT=${DEVTOOLS_PORT:-9223}
here=${0:A:h}

case "${1:-}" in
  install)
    tarball=${2:-}
    if [[ -z "$tarball" ]]; then
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
    # run-on-frame starts in $HOME on the Frame, so the profile path is relative.
    exec "$here/run-on-frame.sh" -- '~/chromium-xr/chrome' \
      --user-data-dir=.config/chromium-xr \
      --enable-features=OpenXR \
      --remote-debugging-port="$DEVTOOLS_PORT" \
      "${2:-https://immersive-web.github.io/webxr-samples/}"
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
  *) sed -n '2,13p' "$0"; exit 2 ;;
esac
