"""Connect this computer to the Steam Frame: find it, create a key, add a `Host frame`
alias to ~/.ssh/config and copy the key over, asking for the Developer Mode
password once. The Linux and Windows twin of scripts/connect.sh (which the Mac
app uses); same config block, so either can re-run over the other. Idempotent.

Usage: python3 ui/frame_connect.py [HOST_OR_IP[:PORT]]
Env:   FRAME_USER (default steamos), FRAME_ALIAS (default frame)
"""
import base64
import os
import platform
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

FRAME_USER = os.environ.get("FRAME_USER", "steamos")
FRAME_ALIAS = os.environ.get("FRAME_ALIAS", "frame")
SSH_DIR = Path.home() / ".ssh"
KEY = SSH_DIR / "id_ed25519_frame"
CONFIG = SSH_DIR / "config"
# Both go into ~/.ssh/config, so nothing that could add a line or a directive.
for _name, _value in (("FRAME_ALIAS", FRAME_ALIAS), ("FRAME_USER", FRAME_USER)):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", _value):
        sys.exit(f"{_name} must be a plain name, not {_value!r}")
BEGIN = f"# >>> steam-frame ({FRAME_ALIAS}) >>>"
END = f"# <<< steam-frame ({FRAME_ALIAS}) <<<"

# Appends the key from stdin unless it's already there. base64 keeps it intact
# through Windows' command-line quoting.
ADD_KEY = """umask 077
mkdir -p ~/.ssh
k=$(cat)
grep -qxF "$k" ~/.ssh/authorized_keys 2>/dev/null || printf '%s\\n' "$k" >> ~/.ssh/authorized_keys
"""
ADD_KEY_CMD = 'sh -c "$(echo %s | base64 -d)"' % base64.b64encode(ADD_KEY.encode()).decode()


def say(msg):
    print(msg, flush=True)


def split_port(arg):
    """"host:2222" -> ("host", 2222); anything else (IPv6 too) keeps port 22."""
    host, sep, port = arg.rpartition(":")
    if sep and port.isdigit() and ":" not in host:
        return host, int(port)
    return arg, 22


def port_open(host, port=22):
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:%-]*")


def pick_host(arg):
    if arg and not HOST_RE.fullmatch(arg):
        say(f"  - {arg!r} isn't a host name or IP address")
        return None
    for cand in [arg] if arg else [f"{FRAME_ALIAS}.local", FRAME_ALIAS]:
        host, port = split_port(cand)
        if port_open(host, port):
            return host, port
        say(f"  - {cand}: not resolvable or port {port} closed")
    return None


def make_ssh_dir():
    # Windows: no mode. Python 3.12.4+ turns 0o700 into an owner-only ACL, which locks
    # the user out if the folder's owner is Administrators; the profile's ACL suffices.
    if os.name == "nt":
        SSH_DIR.mkdir(exist_ok=True)
    else:
        SSH_DIR.mkdir(mode=0o700, exist_ok=True)


def write_config(host, port=22):
    """Replace our managed block and put it first: ssh uses the first value it sees per
    option. The trailing "Host *" returns the rest of the file to global scope."""
    make_ssh_dir()
    old = CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else ""
    kept, skip = [], False
    for line in old.splitlines():
        if line == BEGIN:
            skip = True
        elif line == END:
            skip = False
        elif not skip:
            kept.append(line)
    block = [BEGIN, f"Host {FRAME_ALIAS}", f"  HostName {host}", *([f"  Port {port}"] if port != 22 else []),
             f"  User {FRAME_USER}",
             "  IdentityFile ~/.ssh/id_ed25519_frame", "  IdentitiesOnly yes",
             "  ServerAliveInterval 30", "Host *", END]
    tmp = CONFIG.with_name("config.frame-control.tmp")
    tmp.write_text("\n".join(block + kept) + "\n", encoding="utf-8")
    if os.name != "nt":
        tmp.chmod(0o600)
    # On Windows a running ssh.exe (Frame Control's own, say) keeps the config open
    # and locked, so the swap can fail for a moment; keep trying for a while.
    for attempt in range(60):
        try:
            os.replace(tmp, CONFIG)
            return
        except PermissionError:
            if attempt == 0:
                say("    ~/.ssh/config is in use by another ssh; waiting for it...")
            time.sleep(0.5)
    tmp.unlink(missing_ok=True)
    raise SystemExit("~/.ssh/config stayed locked by another program. Quit Frame Control "
                     "and any ssh windows, then run the setup again.")


def key_login_works():
    # accept-new: trust a first-seen host key (as the copy step does); a changed one still fails.
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                           "-o", "StrictHostKeyChecking=accept-new", FRAME_ALIAS, "true"],
                          capture_output=True).returncode == 0


def main(argv):
    if argv and argv[0] in ("-h", "--help"):
        sys.exit(__doc__)
    say("==> Looking for the Steam Frame")
    found = pick_host(argv[0] if argv else None)
    while not found:
        say("Could not reach the Frame over SSH.")
        say("Check: Developer Mode on and a user password set; same network; no client isolation.")
        try:
            typed = input("Type the Frame's IP address (Quick Settings shows it), or press Enter to quit: ").strip()
        except EOFError:
            typed = ""
        if not typed:
            return 1
        found = pick_host(typed)
    host, port = found
    say(f"    found: {host}" + (f" port {port}" if port != 22 else ""))

    say("==> SSH key")
    make_ssh_dir()
    if KEY.exists():
        say(f"    exists: {KEY}")
    else:
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
                        f"{platform.node() or 'computer'}->steam-frame", "-f", str(KEY)], check=True)
        say(f"    created {KEY}")

    say(f"==> ~/.ssh/config alias '{FRAME_ALIAS}' -> {host}")
    write_config(host, port)

    say("==> Checking key login")
    if key_login_works():
        say("    key login already works")
    else:
        say("    copying the key: enter the Developer Mode password when asked")
        pub = KEY.with_suffix(".pub").read_text(encoding="utf-8").strip()
        r = subprocess.run(["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "PubkeyAuthentication=no",
                            "-p", str(port), f"{FRAME_USER}@{host}", ADD_KEY_CMD], input=pub + "\n", text=True)
        if r.returncode != 0 or not key_login_works():
            say("Key login still isn't working. Check the password and run this again.")
            return 1
        say("    key login OK")
    say(f"\nDone. Frame Control can reach the Frame now. In a terminal: ssh {FRAME_ALIAS}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
