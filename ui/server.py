#!/usr/bin/env python3
"""Frame Control: a small local web UI for managing the Steam Frame from the Mac.

Stdlib only. Listens on 127.0.0.1 and talks to the headset through the `frame`
SSH alias set up by scripts/connect.sh, reusing the scripts in ../scripts.

Usage: ui/server.py [--port 47810]   (normally started by scripts/frame-ui.sh)
Env:   FRAME_ALIAS (default frame)
"""
import argparse
import http.client
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import frame_android
import frame_catalog
import frame_store

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
FRAME = os.environ.get("FRAME_ALIAS", "frame")
# Reuse one SSH connection for the frequent status/screenshot calls. /tmp, not
# $TMPDIR: macOS's per-user temp path overflows the unix socket path limit.
CONTROL = f"/tmp/frame-ui-{os.getuid()}-%C"
MUX = ["ssh", "-o", "BatchMode=yes", "-o", f"ControlPath={CONTROL}"]
# Commands use the master when it's up and connect directly when it isn't.
SSH = [*MUX, "-o", "ControlMaster=no", "-o", "ConnectTimeout=5"]

# Android helpers share the multiplexed connection when it's up.
frame_android.SSH_OPTS = SSH[1:]

APPID = re.compile(r"^\d{1,10}$")
FLATPAK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+){2,}$")
MAX_UPLOAD = 8 * 1024**3
MAX_JSON = 1024**2

# gamescope writes the PNG asynchronously; wait until its size stops changing.
SCREENSHOT = r"""
set -eu
f=$(mktemp /tmp/frame-ui-XXXXXX.png)
trap 'rm -f "$f"' EXIT
XDG_RUNTIME_DIR=/run/user/$(id -u) WAYLAND_DISPLAY=gamescope-0 gamescopectl screenshot "$f" >/dev/null 2>&1
last=-1
for i in $(seq 1 50); do
  sleep 0.1
  size=$(stat -c %s "$f" 2>/dev/null || echo 0)
  if [ "$size" -gt 0 ] && [ "$size" = "$last" ]; then cat "$f"; exit 0; fi
  last=$size
done
echo "gamescope did not write a screenshot" >&2
exit 1
"""


class Failure(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


_master_lock = threading.Lock()
_master = None


def ensure_master():
    """Start the shared SSH connection if it isn't up (one attempt at a time).

    No ConnectTimeout here: with it, OpenSSH's master takes ~5s to open its socket.
    """
    global _master
    def up():
        try:
            return subprocess.run([*MUX, "-O", "check", FRAME], capture_output=True,
                                  timeout=5).returncode == 0
        except subprocess.TimeoutExpired:
            return False

    with _master_lock:
        if up() or (_master and _master.poll() is None):
            return
        # Keepalives make a dead link (Frame asleep, off Wi-Fi) exit within ~10s,
        # so the next request starts a fresh master.
        _master = subprocess.Popen([*MUX, "-o", "ControlMaster=yes", "-o", "ServerAliveInterval=5",
                                    "-o", "ServerAliveCountMax=2", "-N", FRAME],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(60):
            if up() or _master.poll() is not None:
                return
            time.sleep(0.05)


def ssh(remote, *, stdin=None, timeout=30, text=True):
    try:
        ensure_master()
        r = subprocess.run([*SSH, FRAME, remote], input=stdin, capture_output=True,
                           text=text, errors="replace" if text else None, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Failure(f"Timed out talking to {FRAME}")
    if r.returncode != 0:
        err = (r.stderr or r.stdout) if text else (r.stderr or r.stdout).decode(errors="replace")
        failure = Failure(strip_ansi(err).strip() or f"ssh exited {r.returncode}")
        failure.stdout = r.stdout if text else r.stdout.decode(errors="replace")
        raise failure
    return r.stdout


def script(name, *args, stdin=None, timeout=900):
    """Run one of ../scripts and return its combined output."""
    try:
        r = subprocess.run([str(SCRIPTS / name), *args], input=stdin, text=True, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           env={**os.environ, "FRAME_ALIAS": FRAME})
    except subprocess.TimeoutExpired:
        raise Failure(f"{name} timed out")
    out = strip_ansi(r.stdout).strip()
    if r.returncode != 0:
        raise Failure(out or f"{name} exited {r.returncode}")
    return out


def strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\r", "", s)


def terminal(command):
    """Open Terminal.app running `command` (for anything needing a password)."""
    as_str = command.replace("\\", "\\\\").replace('"', '\\"')
    r = subprocess.run(["osascript", "-e", 'tell application "Terminal"',
                        "-e", f'do script "{as_str}"', "-e", "activate", "-e", "end tell"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # Usually macOS Automation consent for Terminal was denied.
        raise Failure(f"Couldn't open Terminal: {r.stderr.strip()}", 500)


def open_app(name, fallback_url):
    if subprocess.run(["open", "-a", name], capture_output=True).returncode == 0:
        return f"Opened {name}"
    subprocess.run(["open", fallback_url])
    return f"{name} isn't installed; opened its download page"


# ---- actions ---------------------------------------------------------------

def status(_body):
    return json.loads(ssh("python3 -", stdin=(HERE / "frame_status.py").read_text(), timeout=20))


def headset_view():
    """Both eyes as SteamVR composites them (see frame_vrshot.py); PNG bytes."""
    # `timeout`: VR_Init can block if SteamVR is restarting.
    out = ssh("timeout 15 python3 -", stdin=(HERE / "frame_vrshot.py").read_text(), timeout=30)
    # SteamVR prints its own notices (e.g. about vrwebhelper) on stdout too, so
    # take the last line that is our result object.
    result = {"error": out.strip() or "no output"}
    for line in out.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and ("path" in obj or "error" in obj):
            result = obj
    if "error" in result:
        raise Failure(str(result["error"]))
    path = str(result["path"])
    if not re.fullmatch(r"/tmp/frame-vrcap/shot-\d+-vr\.png", path):
        raise Failure(f"unexpected capture path {path!r}")
    # Captures show whatever was on screen, so delete even if the copy fails.
    try:
        return ssh(f"cat {path}; rc=$?; rm -f {path}; exit $rc", timeout=20, text=False)
    finally:
        try:
            ssh(f"rm -f {path}", timeout=10)
        except Failure:
            pass  # frame_vrshot.py sweeps leftovers on the next capture


def launch(body):
    appid = str(body.get("appid", ""))
    if not APPID.match(appid):
        raise Failure("bad appid", 400)
    ssh(f"steam steam://rungameid/{appid} >/dev/null 2>&1 &")
    return {"message": f"Launching {appid}"}


def steam_frame(*args, timeout=40):
    """Run frame_steam.py on the Frame (it drives the Steam client) and return its JSON."""
    try:
        out = ssh("python3 - " + " ".join(map(shlex.quote, args)),
                  stdin=(HERE / "frame_steam.py").read_text(), timeout=timeout)
    except Failure as e:
        # frame_steam.py prints {"error": ...} on stdout when it fails, but ssh()
        # reports stderr instead if there was any, so look in both.
        for line in [*reversed(getattr(e, "stdout", "").splitlines()), *reversed(str(e).splitlines())]:
            try:
                raise Failure(json.loads(line)["error"]) from None
            except (ValueError, KeyError, TypeError):
                continue
        raise
    return json.loads(out)


def steam(body):
    """Steam games: install an owned game, or open its store page in the headset."""
    appid, action = str(body.get("appid", "")), body.get("action")
    if not APPID.match(appid):
        raise Failure("bad appid", 400)
    if action not in ("install", "store"):
        raise Failure("action must be install or store", 400)
    return steam_frame(action, appid)


def steam_search(query):
    q = parse_qs(query)
    cc = (q.get("cc") or [""])[0].upper()
    if not re.fullmatch(r"[A-Z]{2}", cc):
        raise Failure("cc must be a two-letter country code", 400)
    try:
        return {"results": frame_store.search((q.get("q") or [""])[0], cc)}
    except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException) as e:
        raise Failure(f"Steam store search failed: {e}")


def set_volume(body):
    # Validate everything before touching the headset.
    level = None
    if "level" in body:
        level = float(body["level"])
        if not 0 <= level <= 1:
            raise Failure("level must be 0..1", 400)
    if "muted" in body:
        ssh(f"wpctl set-mute @DEFAULT_AUDIO_SINK@ {1 if body['muted'] else 0}")
    if level is not None:
        ssh(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {level:.2f}")
    return {"message": "Volume updated"}


def clipboard(body):
    if body.get("fromMac"):
        return {"message": script("paste-to-frame.sh", timeout=30)}
    text = body.get("text")
    if not isinstance(text, str) or not text:
        raise Failure("nothing to send", 400)
    return {"message": script("paste-to-frame.sh", "-", stdin=text, timeout=30)}


def flatpak(body):
    app, action = str(body.get("id", "")), body.get("action")
    if not FLATPAK_ID.match(app):
        raise Failure("bad Flatpak app ID", 400)
    if action == "install":
        return {"message": script("install-apps.sh", app)}
    if action == "uninstall":
        out = ssh(f"flatpak uninstall --user -y -- {shlex.quote(app)}", timeout=300)
        return {"message": strip_ansi(out).strip() or f"Removed {app}"}
    raise Failure("action must be install or uninstall", 400)


def open_thing(body):
    what = body.get("what")
    alias = shlex.quote(FRAME)
    if what == "terminal":
        terminal(f"ssh {alias}")
        return {"message": "Opened an SSH session in Terminal"}
    if what in ("reboot", "poweroff", "suspend"):
        # logind answers "challenge" over SSH, so sudo (and the password) is needed.
        terminal(f"ssh -t {alias} sudo systemctl {what}")
        return {"message": f"Confirm with the Developer Mode password in Terminal to {what}"}
    if what == "steamlink":
        return {"message": open_app("Steam Link", "https://store.steampowered.com/remoteplay")}
    if what == "rdp":
        return {"message": open_app("Windows App", "https://apps.apple.com/app/windows-app/id1295203466")}
    if what == "sftp":
        terminal(f"sftp {alias}")
        return {"message": "Opened an SFTP session in Terminal"}
    raise Failure("unknown target", 400)


def android(body):
    """Android apps, each in its own persistent Lepton instance (frame_android.py)."""
    action, pkg = body.get("action"), str(body.get("package", ""))
    ensure_master()
    try:
        if action == "install":
            m = frame_catalog.install(pkg)
            return {"message": f"Installed {m['label']}. It's in the Steam library; launching it opens its own panel.", "app": m}
        if action in ("launch", "stop"):
            m = getattr(frame_android, action)(pkg)
            return {"message": f"{'Launching' if action == 'launch' else 'Stopped'} {m['label']}"}
        if action == "remove":
            m = frame_android.remove(pkg, keep_data=bool(body.get("keepData")))
            return {"message": f"Removed {m['label']}"}
        if action == "probe":
            r = frame_catalog.probe_and_report(pkg)
            word = {"runs": "runs", "crashes": "crashed", "instance_failed": "didn't start"}.get(r["result"], r["result"])
            return {"message": f"{pkg} {word}" + (f": {r['detail']}" if r.get("detail") else ""), "probe": r}
        if action == "report":
            # Any APK, not only catalogue or installed ones: package, did it work, how it was run.
            r = frame_catalog.add_report(pkg, body.get("version"), rating=body.get("rating"),
                                         notes=str(body.get("notes") or ""),
                                         runtime=body.get("runtime") or "instance",
                                         label=body.get("label"), source=body.get("source"))
            name = r.get("label") or pkg
            return {"message": f"Saved your report for {name}", "report": r}
    except frame_android.FrameError as e:
        raise Failure(str(e))
    raise Failure("unknown action", 400)


# ---- Android display (wm size / wm density / font_scale over ADB) -----------
#
# Each running Lepton instance listens for ADB on the Frame (5555 is Lepton
# Development; own-instance apps get the next free port). ADB goes through a
# dedicated SSH forward that lives only for the request, like
# scripts/install-apk.sh, and is always torn down with an adb disconnect.

ADB_PORTS = range(5555, 5600)
SIZE_RE = re.compile(r"^(\d{3,4})x(\d{3,4})$")
DENSITY_RANGE = (120, 640)
WIDTH_RANGE, HEIGHT_RANGE = (640, 3840), (360, 2160)
FONT_RANGE = (0.5, 2.0)
KNOWN_LABELS = {"com.t3tools.t3code": "T3 Code", "org.fdroid.fdroid": "F-Droid"}
# One ADB session at a time: requests are rare, and it keeps adb's state simple.
_adb_lock = threading.Lock()
_live_tunnels = set()  # ssh processes to kill if the server stops mid-request


def adb_path():
    for cand in (os.environ.get("ADB"), shutil.which("adb"), "/opt/homebrew/bin/adb",
                 str(Path.home() / ".homebrew/bin/adb"), "/usr/local/bin/adb"):
        if cand and os.access(cand, os.X_OK):
            return cand
    raise Failure("adb missing on the Mac: brew install android-platform-tools", 500)


def adb(adb_bin, *args, timeout=20):
    try:
        r = subprocess.run([adb_bin, *args], capture_output=True, text=True,
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Failure(f"adb {' '.join(args[-2:])} timed out")
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        raise Failure(out or f"adb exited {r.returncode}")
    return out


def free_local_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AdbTunnel:
    """SSH forwards from Mac loopback to Frame ADB ports, plus adb connections.

    `with AdbTunnel([5555, 5557]) as t: t.shell(5555, "wm size")`. On exit it
    disconnects adb and kills the ssh process, whatever happened inside.
    """

    def __init__(self, ports):
        self.remote = list(ports)
        self.local = {}
        self.proc = None
        self.adb = adb_path()

    def __enter__(self):
        if not _adb_lock.acquire(timeout=60):
            raise Failure("another Android display request is still running; try again", 503)
        try:
            self._open()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def _open(self):
        try:
            self._forward()
        except Failure:
            # A local port picked by free_local_port() can be taken before ssh
            # binds it (ExitOnForwardFailure turns that into an error): retry once.
            self._stop_ssh()
            self._forward()
        self.failed = {}
        for p in self.remote:
            out = adb(self.adb, "connect", self.serial(p), timeout=15)
            # adb connect exits 0 even when it fails; check what it says. Keep
            # going so one stuck port doesn't hide the healthy instances.
            if "connected to" not in out:
                self.failed[p] = f"adb couldn't connect to Frame port {p}: {out}"

    def _forward(self):
        self.local = {p: free_local_port() for p in self.remote}
        fwd = [a for p, lp in self.local.items() for a in ("-L", f"127.0.0.1:{lp}:127.0.0.1:{p}")]
        # Its own connection (ControlPath=none), so killing it drops the forwards.
        self.proc = _proc = subprocess.Popen(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ControlPath=none",
             "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=5", "-N", *fwd, FRAME],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _live_tunnels.add(_proc)
        deadline = time.time() + 12
        pending = set(self.local.values())
        while pending:
            if self.proc.poll() is not None:
                err = self.proc.stderr.read().decode(errors="replace").strip()
                raise Failure(f"ADB tunnel failed: {err or 'ssh exited ' + str(self.proc.returncode)}")
            if time.time() > deadline:
                raise Failure("ADB tunnel didn't come up within 12s")
            for lp in list(pending):
                try:
                    socket.create_connection(("127.0.0.1", lp), timeout=0.5).close()
                    pending.discard(lp)
                except OSError:
                    pass
            if pending:
                time.sleep(0.1)

    def serial(self, port):
        return f"127.0.0.1:{self.local[port]}"

    def shell(self, port, command, timeout=20):
        if port in getattr(self, "failed", {}):
            raise Failure(self.failed[port])
        return adb(self.adb, "-s", self.serial(port), "shell", command, timeout=timeout)

    def _stop_ssh(self):
        proc, self.proc = self.proc, None
        if not proc:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(5)
        except OSError:
            pass
        finally:
            _live_tunnels.discard(proc)
            if proc.stderr:
                proc.stderr.close()

    def __exit__(self, *exc):
        try:
            # Tunnel first: it's what could outlive us. `adb disconnect` only
            # talks to the local adb server, so it works without the tunnel.
            self._stop_ssh()
            for p in self.local:
                try:
                    subprocess.run([self.adb, "disconnect", self.serial(p)], capture_output=True, timeout=10)
                except (subprocess.TimeoutExpired, OSError):
                    pass
        finally:
            _adb_lock.release()
        return False


DISPLAY_READ = "echo @@pkgs; pm list packages -3; echo @@size; wm size; echo @@density; wm density; " \
               "echo @@font; settings get system font_scale"


def parse_display(out):
    sec, parts = None, {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("@@"):
            sec = line[2:]
            parts[sec] = []
        elif sec and line:
            parts[sec].append(line)

    def pick(lines, key):
        for line in lines:
            if line.lower().startswith(key) and ":" in line:
                return line.split(":", 1)[1].strip()
        return None

    size, density = parts.get("size", []), parts.get("density", [])
    font = (parts.get("font") or ["null"])[0]
    try:
        font_scale = None if font == "null" else float(font)
    except ValueError:
        font_scale = None
    phys_d, over_d = pick(density, "physical density"), pick(density, "override density")
    return {
        "packages": sorted(l.split(":", 1)[1] for l in parts.get("pkgs", []) if l.startswith("package:")),
        "physicalSize": pick(size, "physical size"),
        "overrideSize": pick(size, "override size"),
        "physicalDensity": int(phys_d) if phys_d and phys_d.isdigit() else None,
        "overrideDensity": int(over_d) if over_d and over_d.isdigit() else None,
        # null means never set, which Android treats as 1.0.
        "fontScale": font_scale,
    }


def lepton_ports():
    """Frame ADB ports (5555-5599) that are listening now, with container names and app labels."""
    out = ssh("ss -ltnH; echo @@podman; podman ps --format '{{.Names}} {{.Labels.adb_port}}' 2>/dev/null; "
              f"echo @@meta; for f in {frame_android.APPS_DIR}/*/meta.json; do [ -f \"$f\" ] && cat \"$f\" && echo @@m; done; true",
              timeout=20)
    listen, _, rest = out.partition("@@podman")
    podman, _, meta = rest.partition("@@meta")
    ports = set()
    for line in listen.splitlines():
        cols = line.split()
        if len(cols) >= 4:
            port = cols[3].rsplit(":", 1)[-1]
            if port.isdigit() and int(port) in ADB_PORTS:
                ports.add(int(port))
    containers = {}
    for line in podman.splitlines():
        cols = line.split()
        if len(cols) == 2 and cols[1].isdigit():
            containers[int(cols[1])] = cols[0]
    labels = dict(KNOWN_LABELS)
    for chunk in meta.split("@@m"):
        try:
            m = json.loads(chunk)
            labels[str(m["package"])] = str(m["label"])
        except (ValueError, KeyError, TypeError):
            pass
    return sorted(ports), containers, labels


def android_displays():
    ports, containers, labels = lepton_ports()
    if not ports:
        return {"instances": []}
    instances = []
    with AdbTunnel(ports) as t:
        for p in ports:
            item = {"port": p, "container": containers.get(p)}
            try:
                item.update(parse_display(t.shell(p, DISPLAY_READ)))
            except Failure as e:
                item["error"] = str(e)
            item["labels"] = {pkg: labels[pkg] for pkg in item.get("packages", []) if pkg in labels}
            instances.append(item)
    return {"instances": instances}


def android_display(body):
    port = body.get("port")
    if type(port) is not int or port not in ADB_PORTS:
        raise Failure(f"port must be an integer {ADB_PORTS.start}-{ADB_PORTS.stop - 1}", 400)
    cmds = []

    size = body.get("size")
    if size is not None:
        if size == "reset":
            cmds.append("wm size reset")
        else:
            m = SIZE_RE.fullmatch(size) if isinstance(size, str) else None
            if not m:
                raise Failure("size must be WIDTHxHEIGHT (e.g. 2560x1440) or \"reset\"", 400)
            w, h = int(m[1]), int(m[2])
            if not (WIDTH_RANGE[0] <= w <= WIDTH_RANGE[1] and HEIGHT_RANGE[0] <= h <= HEIGHT_RANGE[1]):
                raise Failure(f"size must be {WIDTH_RANGE[0]}-{WIDTH_RANGE[1]} wide and "
                              f"{HEIGHT_RANGE[0]}-{HEIGHT_RANGE[1]} high", 400)
            cmds.append(f"wm size {w}x{h}")

    density = body.get("density")
    if density is not None:
        if density == "reset":
            cmds.append("wm density reset")
        elif type(density) is int and DENSITY_RANGE[0] <= density <= DENSITY_RANGE[1]:
            cmds.append(f"wm density {density}")
        else:
            raise Failure(f"density must be an integer {DENSITY_RANGE[0]}-{DENSITY_RANGE[1]} or \"reset\"", 400)

    font = body.get("fontScale")
    if font is not None:
        if font == "reset":
            # Applying a config change (e.g. the wm resets just before) writes
            # font_scale=1.0 back asynchronously, so delete again once it settles.
            cmds.append("settings delete system font_scale; sleep 1; settings delete system font_scale")
        elif type(font) in (int, float) and FONT_RANGE[0] <= font <= FONT_RANGE[1]:
            cmds.append(f"settings put system font_scale {round(float(font), 3):g}")
        else:
            raise Failure(f"fontScale must be a number {FONT_RANGE[0]}-{FONT_RANGE[1]} or \"reset\"", 400)

    if not cmds:
        raise Failure("nothing to change: give density, size or fontScale", 400)
    ports, _, _ = lepton_ports()
    if port not in ports:
        raise Failure(f"no Lepton instance is listening on Frame port {port}", 404)
    with AdbTunnel([port]) as t:
        for c in cmds:
            out = t.shell(port, c)
            # wm prints usage or an exception on failure but may still exit 0.
            if re.search(r"exception|error|usage", out, re.I):
                raise Failure(f"{c}: {out}")
        now = parse_display(t.shell(port, DISPLAY_READ))
    now["port"] = port
    return {"message": f"Port {port}: " + "; ".join(c.split(";")[0] for c in cmds), "display": now}


POST = {"/api/android/display": android_display, "/api/android": android,"/api/launch": launch, "/api/steam": steam, "/api/volume": set_volume, "/api/clipboard": clipboard,
        "/api/flatpak": flatpak, "/api/open": open_thing}


# ---- HTTP ------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "FrameControl/1"
    timeout = 60  # per socket operation, so a stalled client can't hold a thread

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, fmt % args))

    def local_request(self):
        # Blocks DNS rebinding (Host) and cross-site form posts (custom header
        # forces a CORS preflight, which this server never approves).
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            self.send_json({"error": "forbidden host"}, 403)
            return False
        # All of /api/*, not just POST: an <img> on any website could otherwise
        # trigger a headset capture and display it.
        api = urlparse(self.path).path.startswith("/api/")
        if (self.command == "POST" or api) and self.headers.get("X-Frame-UI") != "1":
            self.send_json({"error": "missing X-Frame-UI header"}, 403)
            return False
        return True

    def send_bytes(self, data, ctype, status=200, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        # Nobody may frame the UI (clickjacking).
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj, status=200):
        self.send_bytes(json.dumps(obj).encode(), "application/json", status)

    def do_GET(self):
        if not self.local_request():
            return
        url = urlparse(self.path)
        path = url.path
        try:
            if path in ("/", "/index.html"):
                self.send_bytes((HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/android":
                ensure_master()
                self.send_json({"apps": frame_android.list_apps()})
            elif path == "/api/android/displays":
                self.send_json(android_displays())
            elif path == "/api/android/reports":
                self.send_json({"reports": frame_catalog.recent_reports()})
            elif path == "/api/android/catalog":
                self.send_json({"apps": frame_catalog.catalog()})
            elif path == "/api/status":
                self.send_json(status({}))
            elif path == "/api/steam/owned":
                self.send_json(steam_frame("owned"))
            elif path == "/api/steam/search":
                self.send_json(steam_search(url.query))
            elif path == "/api/screenshot" and parse_qs(url.query).get("view") == ["headset"]:
                self.send_bytes(headset_view(), "image/png", headers=[("X-Capture-Source", "steamvr")])
            elif path == "/api/screenshot":
                self.send_bytes(ssh(SCREENSHOT, timeout=20, text=False), "image/png",
                                headers=[("X-Capture-Source", "gamescope")])
            else:
                self.send_json({"error": "not found"}, 404)
        except Failure as e:
            self.send_json({"error": str(e)}, e.status)
        except Exception as e:
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        if not self.local_request():
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/upload":
                self.send_json(self.upload())
                return
            handler = POST.get(path)
            if not handler:
                self.send_json({"error": "not found"}, 404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_JSON:
                raise Failure("request body too large", 413)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise Failure("request body must be a JSON object", 400)
            self.send_json(handler(body))
        except Failure as e:
            self.send_json({"error": str(e)}, e.status)
        except (ValueError, TypeError) as e:
            self.send_json({"error": f"bad request: {e}"}, 400)
        except Exception as e:
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    def upload(self):
        """Raw file body. X-Filename names it; X-Mode is 'push', 'apk' (install) or 'apkinfo' (read only)."""
        name = os.path.basename(unquote(self.headers.get("X-Filename", "")))
        mode = self.headers.get("X-Mode", "push")
        length = int(self.headers.get("Content-Length") or 0)
        if not name or name.startswith("."):
            raise Failure("missing filename", 400)
        if length <= 0 or length > MAX_UPLOAD:
            raise Failure("empty or too-large upload", 400)
        if mode in ("apk", "apkinfo") and not name.lower().endswith(".apk"):
            raise Failure("APK install needs a .apk file", 400)
        tmp = Path(tempfile.mkdtemp(prefix="frame-ui-"))
        try:
            dest = tmp / name
            with open(dest, "wb") as f:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(remaining, 1 << 20))
                    if not chunk:
                        raise Failure("upload interrupted", 400)
                    f.write(chunk)
                    remaining -= len(chunk)
            if mode == "apkinfo":
                # Read an APK for a report without installing it.
                try:
                    info = frame_android.apk_info(str(dest))
                except frame_android.FrameError as e:
                    raise Failure(str(e), 400)
                info.pop("icon_png", None)
                try:
                    frame_android.check_installable(info)
                    info["blocker"] = None
                except frame_android.FrameError as e:
                    info["blocker"] = str(e)
                return {"message": f"Read {info['label']} {info['version']}", "apk": info}
            if mode == "apk":
                ensure_master()
                try:
                    m = frame_android.install(str(dest), source=name)
                except frame_android.FrameError as e:
                    raise Failure(str(e), 400)
                return {"message": f"Installed {m['label']} as its own app in the Steam library", "app": m}
            return {"message": script("push.sh", str(dest))}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 47810)))
    args = ap.parse_args()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    print(f"Frame Control on http://127.0.0.1:{args.port}  (alias: {FRAME}; Ctrl-C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # The master was started with -N, so it stays up until told to exit.
        subprocess.run([*MUX, "-O", "exit", FRAME], capture_output=True)
        if _master and _master.poll() is None:
            _master.terminate()
        for proc in list(_live_tunnels):  # ADB forwards of requests cut off mid-way
            if proc.poll() is None:
                proc.terminate()


if __name__ == "__main__":
    main()
