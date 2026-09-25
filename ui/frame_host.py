"""What differs between the computers Frame Control runs on: macOS, Linux, Windows.

Everything here runs on your computer, not the Frame. Python stdlib only.

CLI (used by the Electron app, so terminal handling lives in one place):
  python3 ui/frame_host.py terminal -- CMD [ARG...]   # open CMD in a terminal window
"""
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

MAC = sys.platform == "darwin"
WINDOWS = os.name == "nt"
LINUX = not MAC and not WINDOWS
NAME = "macOS" if MAC else "Windows" if WINDOWS else "Linux"
FILE_MANAGER = "Finder" if MAC else "File Explorer" if WINDOWS else "your file manager"

# Windows' OpenSSH client can't share one connection between commands
# (no ControlMaster), so there each command opens its own.
MUX = not WINDOWS

# Popen() keyword arguments that detach a child from our console and signals.
DETACHED = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS
            else {"start_new_session": True})


class HostError(RuntimeError):
    pass


def data_dir(*parts):
    """Per-user app data: ~/Library/Application Support, %APPDATA% or $XDG_DATA_HOME."""
    if MAC:
        base = Path.home() / "Library" / "Application Support" / "Frame Control"
    elif WINDOWS:
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Frame Control"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "frame-control"
    return base.joinpath(*parts)


def cache_dir(*parts):
    if MAC:
        base = Path.home() / "Library" / "Caches" / "Frame Control"
    elif WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Frame Control" / "Cache"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "frame-control"
    return base.joinpath(*parts)


def control_path():
    """ssh ControlPath for the shared connection, or None where it isn't supported.

    /tmp, not $TMPDIR: macOS's per-user temp path overflows the unix socket path limit.
    """
    return f"/tmp/frame-ui-{os.getuid()}-%C" if MUX else None


def which(name, *extra):
    """First executable among PATH and the extra candidate paths."""
    for cand in (shutil.which(name), *extra):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def install_hint(tool):
    """How to get a missing command-line tool on this computer."""
    hints = {
        "adb": {"mac": "brew install android-platform-tools",
                "win": "winget install Google.PlatformTools",
                "linux": "install your distribution's adb package (e.g. sudo apt install adb)"},
        "aapt2": {"mac": 'brew install --cask android-commandlinetools, then sdkmanager "build-tools;36.0.0"',
                  "win": 'install Android Studio\'s command-line tools, then sdkmanager "build-tools;36.0.0"',
                  "linux": 'install Android\'s command-line tools, then sdkmanager "build-tools;36.0.0"'},
    }
    return hints[tool]["mac" if MAC else "win" if WINDOWS else "linux"]


def android_sdk_dirs():
    """Where the Android SDK usually lives, for adb and aapt2."""
    dirs = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    if MAC:
        dirs += ["~/Library/Android/sdk", "/opt/homebrew/share/android-commandlinetools",
                 "~/.homebrew/share/android-commandlinetools"]
    elif WINDOWS:
        dirs += [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk")]
    else:
        dirs += ["~/Android/Sdk", "/usr/lib/android-sdk"]
    return [os.path.expanduser(d) for d in dirs if d]


def adb():
    exe = "adb.exe" if WINDOWS else "adb"
    extra = [os.path.join(d, "platform-tools", exe) for d in android_sdk_dirs()]
    if MAC:
        extra += ["/opt/homebrew/bin/adb", str(Path.home() / ".homebrew/bin/adb"), "/usr/local/bin/adb"]
    env = os.environ.get("ADB")
    found = (env if env and os.access(env, os.X_OK) else None) or which("adb", *extra)
    if not found:
        raise HostError(f"adb isn't installed on this computer: {install_hint('adb')}")
    return found


def open_path(path):
    """Show a folder or file in the file manager."""
    path = str(path)
    if WINDOWS:
        os.startfile(path)  # noqa: pylint only on Windows
        return
    opener = "open" if MAC else which("xdg-open")
    if not opener:
        raise HostError("xdg-open isn't installed, so the folder can't be opened")
    subprocess.Popen([opener, path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **DETACHED)


open_url = open_path  # the same openers hand URLs to the default browser


def _spawn(argv):
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **DETACHED)


def open_terminal(argv, title="Frame Control"):
    """Run argv in a new terminal window, for anything that asks for a password.

    The window stays open after the command ends, so its output can be read.
    """
    argv = [str(a) for a in argv]
    if MAC:
        command = shlex.join(argv).replace("\\", "\\\\").replace('"', '\\"')
        r = subprocess.run(["osascript", "-e", 'tell application "Terminal"',
                            "-e", f'do script "{command}"', "-e", "activate", "-e", "end tell"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            # Usually macOS Automation consent for Terminal was denied.
            raise HostError(f"Couldn't open Terminal: {r.stderr.strip()}")
        return "Terminal"
    if WINDOWS:
        # `start` gives the command its own console window; cmd /k keeps it open.
        # One hand-built command line: quoting it twice through list2cmdline would
        # produce backslash-escaped quotes, which cmd doesn't understand.
        inner = subprocess.list2cmdline(argv)
        subprocess.Popen(f'cmd.exe /c start "{title}" cmd.exe /k "{inner}"', **DETACHED)
        return "a terminal window"
    script = f'{shlex.join(argv)}; echo; read -r -p "Press Enter to close. " _'
    for name, flag in (("x-terminal-emulator", "-e"), ("gnome-terminal", "--"), ("konsole", "-e"),
                       ("xfce4-terminal", "-x"), ("kitty", None), ("alacritty", "-e"),
                       ("foot", None), ("xterm", "-e")):
        exe = which(name)
        if exe:
            _spawn([exe, *([flag] if flag else []), "bash", "-c", script])
            return name
    raise HostError("No terminal program found (tried gnome-terminal, konsole, xterm and others)")


def clipboard_text():
    """The text on this computer's clipboard."""
    if MAC:
        cmds = [["pbpaste"]]
    elif WINDOWS:
        cmds = [["powershell.exe", "-NoProfile", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"]]
    else:
        cmds = [["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"],
                ["xsel", "--clipboard", "--output"]]
    for cmd in cmds:
        if not shutil.which(cmd[0]):
            continue
        r = subprocess.run(cmd, capture_output=True, timeout=10)
        if r.returncode == 0:
            text = r.stdout.decode("utf-8", errors="replace")
            return text[:-2] if WINDOWS and text.endswith("\r\n") else text
    if LINUX:
        raise HostError("Can't read the clipboard: install wl-clipboard (Wayland) or xclip (X11)")
    raise HostError("Can't read the clipboard")


def ssh_hostname(alias):
    """The real host name an ssh alias points at (`ssh -G`), for non-SSH clients like RDP."""
    try:
        out = subprocess.run(["ssh", "-G", alias], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return alias
    for line in out.splitlines():
        if line.startswith("hostname "):
            return line.split(None, 1)[1].strip()
    return alias


# Apps the UI can hand off to, per platform: (installed-check, launch argv) pairs,
# and where to get the app when none is installed.
def open_steam_link():
    if MAC:
        if subprocess.run(["open", "-a", "Steam Link"], capture_output=True).returncode == 0:
            return "Opened Steam Link"
    elif WINDOWS:
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
            exe = base and os.path.join(base, "Steam Link", "SteamLink.exe")
            if exe and os.path.isfile(exe):
                _spawn([exe])
                return "Opened Steam Link"
    else:
        if which("steamlink"):
            _spawn([which("steamlink")])
            return "Opened Steam Link"
        if which("flatpak") and subprocess.run(["flatpak", "info", "com.valvesoftware.SteamLink"],
                                               capture_output=True).returncode == 0:
            _spawn(["flatpak", "run", "com.valvesoftware.SteamLink"])
            return "Opened Steam Link"
    open_url("https://store.steampowered.com/remoteplay")
    return "Steam Link isn't installed; opened its download page"


def open_rdp(alias):
    """Remote desktop to the Frame's xrdp (user steamos)."""
    host = ssh_hostname(alias)
    if MAC:
        if subprocess.run(["open", "-a", "Windows App"], capture_output=True).returncode == 0:
            return "Opened Windows App"
        open_url("https://apps.apple.com/app/windows-app/id1295203466")
        return "Windows App isn't installed; opened its App Store page"
    if WINDOWS:
        _spawn(["mstsc.exe", f"/v:{host}"])
        return f"Opened Remote Desktop to {host}"
    if which("remmina"):
        _spawn(["remmina", "-c", f"rdp://steamos@{host}"])
        return f"Opened Remmina to {host}"
    for name in ("xfreerdp3", "xfreerdp"):
        if which(name):
            _spawn([name, f"/v:{host}", "/u:steamos", "/dynamic-resolution"])
            return f"Opened FreeRDP to {host}"
    raise HostError("No RDP client found: install Remmina or FreeRDP")


def main(argv):
    if len(argv) >= 3 and argv[0] == "terminal" and argv[1] == "--":
        try:
            print(f"Opened {open_terminal(argv[2:])}")
        except HostError as e:
            sys.exit(str(e))
        return
    sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
