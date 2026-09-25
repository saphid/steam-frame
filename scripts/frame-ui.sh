#!/usr/bin/env zsh
# Mac-side: start Frame Control (ui/server.py) and open it in its own window.
#
# Needs scripts/connect.sh to have been run once. Ctrl-C stops the server.
#
# Usage: scripts/frame-ui.sh [--no-open]
# Env:   PORT (default 47810), FRAME_ALIAS (default frame).
set -euo pipefail

PORT=${PORT:-47810}
here=${0:A:h}
url="http://127.0.0.1:$PORT/"
open_window=1
[[ "${1:-}" == "--no-open" ]] && open_window=0
[[ "${1:-}" == -h || "${1:-}" == --help ]] && { sed -n '2,8p' "$0"; exit 0; }

show() {
  (( open_window )) || return 0
  # A Chrome app window looks like a native app; fall back to the default browser.
  if [[ -d "/Applications/Google Chrome.app" ]]; then
    open -na "Google Chrome" --args --app="$url" --window-size=1400,950
  else
    open "$url"
  fi
}

# The Server header tells our server apart from anything else on the port.
ours() { curl -fsS -D - -o /dev/null "$url" 2>/dev/null | grep -qi '^server: FrameControl'; }

if ours; then
  print "Frame Control is already running at $url"
  show
  exit 0
fi

python3 "$here/../ui/server.py" --port "$PORT" &
server=$!
trap 'kill $server 2>/dev/null' EXIT INT TERM
for i in {1..50}; do
  ours && break
  kill -0 $server 2>/dev/null || { print -u2 "Server exited (port $PORT in use? try PORT=... $0)"; exit 1; }
  (( i == 50 )) && { print -u2 "Server didn't start"; exit 1; }
  sleep 0.1
done
show
wait $server
