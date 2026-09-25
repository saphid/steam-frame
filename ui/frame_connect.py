"""Connect this computer to the Steam Frame: find it, create a key, add a `Host frame`
alias to ~/.ssh/config and copy the key over, asking for the Developer Mode
password once. The Linux and Windows twin of scripts/connect.sh (which the Mac
app uses); same config block, so either can re-run over the other. Idempotent.

Usage: python3 ui/frame_connect.py [HOST_OR_IP]
Env:   FRAME_USER (default steamos), FRAME_ALIAS (default frame)
"""
import base64
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

FRAME_USER = os.environ.get("FRAME_USER", "steamos")
FRAME_ALIAS = os.environ.get("FRAME_ALIAS", "frame")
SSH_DIR = Path.home() / ".ssh"
KEY = SSH_DIR / "id_ed25519_frame"
CONFIG = SSH_DIR / "config"
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


def port_open(host):
    try:
        with socket.create_connection((host, 22), timeout=3):
            return True
    except OSError:
        return False


def pick_host(arg):
    for host in [arg] if arg else [f"{FRAME_ALIAS}.local", FRAME_ALIAS]:
        if port_open(host):
            return host
        say(f"  - {host}: not resolvable or port 22 closed")
    return None


def write_config(host):
    """Replace our managed block and put it first: ssh uses the first value it sees per
    option. The trailing "Host *" returns the rest of the file to global scope."""
    SSH_DIR.mkdir(mode=0o700, exist_ok=True)
    old = CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else ""
    kept, skip = [], False
    for line in old.splitlines():
        if line == BEGIN:
            skip = True
        elif line == END:
            skip = False
        elif not skip:
            kept.append(line)
    block = [BEGIN, f"Host {FRAME_ALIAS}", f"  HostName {host}", f"  User {FRAME_USER}",
             "  IdentityFile ~/.ssh/id_ed25519_frame", "  IdentitiesOnly yes",
             "  ServerAliveInterval 30", "Host *", END]
    CONFIG.write_text("\n".join(block + kept) + "\n", encoding="utf-8")
    if os.name != "nt":
        CONFIG.chmod(0o600)


def key_login_works():
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", FRAME_ALIAS, "true"],
                          capture_output=True).returncode == 0


def main(argv):
    if argv and argv[0] in ("-h", "--help"):
        sys.exit(__doc__)
    say("==> Looking for the Steam Frame")
    host = pick_host(argv[0] if argv else None)
    while not host:
        say("Could not reach the Frame on port 22.")
        say("Check: Developer Mode on and a user password set; same network; no client isolation.")
        try:
            typed = input("Type the Frame's IP address (Quick Settings shows it), or press Enter to quit: ").strip()
        except EOFError:
            typed = ""
        if not typed:
            return 1
        host = pick_host(typed)
    say(f"    found: {host}")

    say("==> SSH key")
    SSH_DIR.mkdir(mode=0o700, exist_ok=True)
    if KEY.exists():
        say(f"    exists: {KEY}")
    else:
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
                        f"{platform.node() or 'computer'}->steam-frame", "-f", str(KEY)], check=True)
        say(f"    created {KEY}")

    say(f"==> ~/.ssh/config alias '{FRAME_ALIAS}' -> {host}")
    write_config(host)

    say("==> Checking key login")
    if key_login_works():
        say("    key login already works")
    else:
        say("    copying the key: enter the Developer Mode password when asked")
        pub = KEY.with_suffix(".pub").read_text(encoding="utf-8").strip()
        r = subprocess.run(["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "PubkeyAuthentication=no",
                            f"{FRAME_USER}@{host}", ADD_KEY_CMD], input=pub + "\n", text=True)
        if r.returncode != 0 or not key_login_works():
            say("Key login still isn't working. Check the password and run this again.")
            return 1
        say("    key login OK")
    say(f"\nDone. Frame Control can reach the Frame now. In a terminal: ssh {FRAME_ALIAS}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
