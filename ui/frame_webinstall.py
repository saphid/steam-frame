"""Install links from websites: frame-control://install?manifest=URL or ?url=URL.

The app hands the link to the page, the page shows what it will install and
asks the user first, and only then does this module download the file and pass
it to the installer for its type (dispatch()). See docs/web-install.md.

A manifest is the same JSON FrameDrop uses, so one works for both tools:
    {"schema": "framedrop.install/v1", "name": "My Game",
     "files": [{"url": "https://cdn.example.com/mygame-arm64.apk", "sha256": "..."}]}
"frame-control.install/v1" is accepted with the same shape.

Rules: HTTPS only, except http(s)://localhost or 127.0.0.1 for testing, and then
only with FRAME_CONTROL_LOCAL_LINKS=1 set and when the link itself points there.
No credentials in URLs, no private, loopback, link-local or CGNAT addresses
(checked on every redirect, and the connection goes to the address that was
checked, so DNS can't change it in between). The file URL must end in a file name.

Python stdlib only, 3.9 compatible.
"""
import hashlib
import http.client
import ipaddress
import json
import os
import errno
import re
import select
import socket
import ssl
import tempfile
import time
from urllib.parse import unquote, urljoin, urlsplit

SCHEMAS = ("framedrop.install/v1", "frame-control.install/v1")
MAX_FILE = 4 * 1024**3        # largest download accepted
MAX_MANIFEST = 256 * 1024     # largest manifest accepted
MAX_URL = 2048
MAX_REDIRECTS = 5
TIMEOUT = 30                  # seconds per socket operation
CHUNK = 1 << 20
LOCAL_HOSTS = ("localhost", "127.0.0.1")
# Off by default: otherwise any website could make the app fetch from local services.
LOCAL_LINKS_ENV = "FRAME_CONTROL_LOCAL_LINKS"
USER_AGENT = "FrameControl (+https://github.com/saphid/steam-frame)"
# What dispatch() can install, by file extension.
KINDS = {".apk": "apk", ".zip": "title", ".exe": "title"}
KIND_LABEL = {"apk": "Android app (APK)", "title": "Linux/Windows title"}
SHA256 = re.compile(r"[0-9a-fA-F]{64}")
CGNAT = ipaddress.ip_network("100.64.0.0/10")
# connect_ex() results meaning "still connecting" (the last is Windows' WSAEWOULDBLOCK).
_CONNECTING = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, getattr(errno, "WSAEWOULDBLOCK", 10035)}

# Swapped out by the tests, which have no network.
_getaddrinfo = socket.getaddrinfo


class WebInstallError(Exception):
    pass


class Cancelled(WebInstallError):
    pass


# ---- URLs -------------------------------------------------------------------

def is_public(ip):
    """True for addresses on the public internet, and nothing a LAN or this computer uses."""
    ip = ipaddress.ip_address(ip)
    if ip.version == 6:
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip.is_site_local:  # fec0::/10: deprecated, but is_global doesn't catch it
            return False
        elif ip.sixtofour and not is_public(ip.sixtofour):
            return False
    if ip.version == 4 and ip in CGNAT:
        return False
    return ip.is_global and not ip.is_multicast


def check_url(url, allow_local=False):
    """Validate a URL against the rules above; returns (scheme, host, port, is_local).

    Resolving the name is left to connect time (see _resolve), so this needs no network.
    """
    if not isinstance(url, str) or not url or len(url) > MAX_URL:
        raise WebInstallError("the link must be a URL of at most %d characters" % MAX_URL)
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise WebInstallError("the URL has spaces or control characters in it")
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError as e:
        raise WebInstallError(f"not a valid URL: {e}")
    scheme = u.scheme.lower()
    if scheme not in ("https", "http"):
        raise WebInstallError(f"only https:// links are allowed, not {scheme or 'a relative URL'}")
    if u.username is not None or u.password is not None or "@" in u.netloc:
        raise WebInstallError("URLs with a user name or password in them aren't allowed")
    host = (u.hostname or "").lower().rstrip(".")
    if not host:
        raise WebInstallError("the URL has no host")
    local = host in LOCAL_HOSTS
    if local and not allow_local:
        raise WebInstallError(f"localhost links are for testing: set {LOCAL_LINKS_ENV}=1, and the link itself must point there")
    if scheme == "http" and not local:
        raise WebInstallError("only https:// is allowed (http:// only for localhost while testing)")
    if not local:
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None and not is_public(literal):
            raise WebInstallError(f"{host} is a private or local address")
    return scheme, host, port or (443 if scheme == "https" else 80), local


def file_name(url):
    """The file name the URL ends in, e.g. mygame-arm64.apk."""
    path = urlsplit(url).path
    name = unquote(path.rsplit("/", 1)[-1])
    if not name or name in (".", "..") or "/" in name or "\\" in name or name.startswith(".") \
            or any(ord(c) < 32 for c in name) or len(name) > 200:
        raise WebInstallError("the file URL must end in a file name, e.g. https://example.com/mygame.apk")
    return name


def file_kind(name):
    ext = os.path.splitext(name.lower())[1]
    kind = KINDS.get(ext)
    if not kind:
        raise WebInstallError(f"{name}: Frame Control installs .apk, .zip and .exe files, not {ext or 'this type'}")
    return kind


def _resolve(host, port, local):
    """One address to connect to; every address the name has must be public."""
    if local:
        return "127.0.0.1"
    try:
        infos = _getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as e:
        raise WebInstallError(f"couldn't look up {host}: {e}")
    ips = [info[4][0].split("%", 1)[0] for info in infos]
    if not ips:
        raise WebInstallError(f"couldn't look up {host}")
    for ip in ips:
        if not is_public(ip):
            raise WebInstallError(f"{host} points to a private or local address ({ip})")
    return ips[0]


# ---- HTTP -------------------------------------------------------------------

class _Abortable:
    """Connects to an address checked beforehand, whatever DNS says by then.

    raw_sock is the socket to shut down to stop the connection from another
    thread (abort()): http.client drops conn.sock once a response will close
    the connection, yet keeps reading the body from it.
    """
    raw_sock = None
    aborted = False

    def _tcp(self):
        """Connect without blocking, so abort() can stop a connect that hangs."""
        sock = socket.socket(socket.AF_INET6 if ":" in self._ip else socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setblocking(False)
            err = sock.connect_ex((self._ip, self.port))
            deadline = time.monotonic() + self.timeout
            while err in _CONNECTING:
                if self.aborted:
                    raise OSError("aborted")
                if time.monotonic() > deadline:
                    raise socket.timeout(f"timed out connecting to {self.host}")
                _, writable, failed = select.select([], [sock], [sock], 0.2)
                if writable or failed:
                    err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if err:
                raise OSError(err, os.strerror(err))
            sock.settimeout(self.timeout)
            self.raw_sock = sock
            if self.aborted:  # abort() ran just now and found nothing to shut down
                raise OSError("aborted")
        except BaseException:
            sock.close()
            raise
        return sock


class _HTTPConnection(_Abortable, http.client.HTTPConnection):
    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = self._tcp()


class _HTTPSConnection(_Abortable, http.client.HTTPSConnection):
    """As above, still verifying the certificate for the host name."""

    def __init__(self, host, ip, port, timeout):
        # urllib's default context, so the app's bundled CA list (frame_host.trust_bundled_cas) applies too.
        super().__init__(host, port, timeout=timeout, context=ssl._create_default_https_context())
        self._ip = ip

    def connect(self):
        # Wrapping detaches the plain socket, so publish the TLS one before the handshake.
        sock = self._context.wrap_socket(self._tcp(), server_hostname=self.host, do_handshake_on_connect=False)
        self.raw_sock = sock
        try:
            if self.aborted:
                raise OSError("aborted")
            sock.do_handshake()
        except (AttributeError, ValueError) as e:
            # abort()'s shutdown() can tear down the TLS state mid-way.
            sock.close()
            if self.aborted:
                raise OSError("aborted")
            raise OSError(str(e))
        except BaseException:
            sock.close()
            raise
        self.sock = sock


def _open(url, allow_local, method="GET", connected=None):
    """(connection, response) for url after redirects, each hop checked. Caller closes the connection.

    connected(conn) gets each connection before it's used, for abort().
    """
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, local = check_url(url, allow_local)
        ip = _resolve(host, port, local)
        cls = _HTTPSConnection if scheme == "https" else _HTTPConnection
        conn = cls(host, ip, port, TIMEOUT)
        if connected:
            connected(conn)
        u = urlsplit(url)
        target = (u.path or "/") + ("?" + u.query if u.query else "")
        try:
            conn.request(method, target, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
            r = conn.getresponse()
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise WebInstallError(f"couldn't reach {host}: {e}")
        if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):
            url = urljoin(url, r.getheader("Location").strip())
            conn.close()
            continue
        if r.status != 200:
            conn.close()
            raise WebInstallError(f"{host} answered HTTP {r.status} {r.reason}".strip())
        return conn, r
    raise WebInstallError(f"more than {MAX_REDIRECTS} redirects")


def _length(r):
    try:
        n = int(r.getheader("Content-Length") or "")
    except ValueError:
        return None
    return n if n >= 0 else None


# ---- manifests --------------------------------------------------------------

def parse_manifest(obj):
    """{"name": ..., "file": {"url", "sha256", "size", "exe"}} from a manifest object."""
    if not isinstance(obj, dict):
        raise WebInstallError("the manifest must be a JSON object")
    schema = obj.get("schema")
    if schema not in SCHEMAS:
        raise WebInstallError(f"unsupported manifest schema {schema!r} (expected {' or '.join(SCHEMAS)})")
    files = obj.get("files")
    if not isinstance(files, list) or not files:
        raise WebInstallError("the manifest has no files")
    if len(files) > 1:
        raise WebInstallError(f"the manifest lists {len(files)} files; Frame Control installs one file per link for now")
    entry = files[0]
    if not isinstance(entry, dict) or not isinstance(entry.get("url"), str) or not entry["url"]:
        raise WebInstallError("the manifest's file has no url")
    sha = entry.get("sha256")
    if sha is not None and (not isinstance(sha, str) or not SHA256.fullmatch(sha)):
        raise WebInstallError("sha256 must be 64 hex digits")
    size = entry.get("size")
    if size is not None and (type(size) is not int or size <= 0):
        raise WebInstallError("size must be a positive integer")
    exe = entry.get("exe")
    if exe is not None and (not isinstance(exe, str) or not exe or len(exe) > 300):
        raise WebInstallError("exe must be a path inside the archive")
    name = obj.get("name")
    if name is not None and not isinstance(name, str):
        raise WebInstallError("name must be a string")
    return {"name": clean_name(name), "file": {"url": entry["url"], "sha256": sha.lower() if sha else None,
                                               "size": size, "exe": exe}}


def clean_name(name):
    name = re.sub(r"[\x00-\x1f\x7f]", "", name or "").strip()
    return name[:120] or None


def fetch_manifest(url, allow_local):
    conn, r = _open(url, allow_local)
    try:
        n = _length(r)
        if n is not None and n > MAX_MANIFEST:
            raise WebInstallError(f"the manifest is over {MAX_MANIFEST // 1024} KB")
        data = r.read(MAX_MANIFEST + 1)
    except (OSError, http.client.HTTPException) as e:
        raise WebInstallError(f"couldn't read the manifest: {e}")
    finally:
        conn.close()
    if len(data) > MAX_MANIFEST:
        raise WebInstallError(f"the manifest is over {MAX_MANIFEST // 1024} KB")
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise WebInstallError("the manifest isn't valid JSON")
    return parse_manifest(obj)


def _head_size(url, allow_local):
    """Content-Length from a HEAD request, or None; only for showing the size up front."""
    try:
        conn, r = _open(url, allow_local, method="HEAD")
    except WebInstallError:
        return None
    try:
        return _length(r)
    finally:
        conn.close()


def plan(manifest=None, url=None):
    """Everything the confirm dialog shows, fetched and checked; nothing is downloaded yet.

    Exactly one of manifest (a manifest URL) or url (a direct file URL).
    """
    if (manifest is None) == (url is None):
        raise WebInstallError("give either manifest or url")
    link = manifest if manifest is not None else url
    # localhost is for testing a link on your own computer: only with the developer
    # switch on, and only for a link that starts there (a public manifest can't
    # point at localhost).
    allow_local = check_url(link, allow_local=os.environ.get(LOCAL_LINKS_ENV) == "1")[3]
    if manifest is not None:
        m = fetch_manifest(manifest, allow_local)
        name, f = m["name"], m["file"]
    else:
        name, f = None, {"url": url, "sha256": None, "size": None, "exe": None}
    _, host, _, _ = check_url(f["url"], allow_local)
    fname = file_name(f["url"])
    kind = file_kind(fname)
    size = f["size"] or _head_size(f["url"], allow_local)
    if size is not None and size > MAX_FILE:
        raise WebInstallError(f"{fname} is {size / 1024**3:.1f} GB; the limit is {MAX_FILE / 1024**3:.0f} GB")
    return {"name": name or fname, "url": f["url"], "file": fname, "kind": kind, "kindLabel": KIND_LABEL[kind],
            "host": host, "linkHost": urlsplit(link).hostname, "size": size, "sha256": f["sha256"],
            "exe": f["exe"], "source": link, "allowLocal": allow_local, "sizeFromManifest": bool(f["size"])}


def abort(conn):
    """Stop conn from another thread (cancel, shutdown): unblocks a read, or makes the connect fail."""
    conn.aborted = True
    sock = conn.raw_sock
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def download(p, dest_dir, progress=None, cancelled=None, connected=None):
    """Download plan p's file into dest_dir; returns its path. Checks the size cap and sha256.

    progress(done, total_or_None) is called as bytes arrive; cancelled() may return True to stop;
    connected(conn) gets each connection before it's used, for abort().
    """
    dest = os.path.join(dest_dir, p["file"])
    try:
        conn, r = _open(p["url"], p["allowLocal"], connected=connected)
    except WebInstallError:
        if cancelled and cancelled():
            raise Cancelled("download cancelled")
        raise
    fd, part = tempfile.mkstemp(prefix=".part-", dir=dest_dir)
    out = os.fdopen(fd, "wb")
    ok = False
    try:
        total = _length(r)
        expected = p["size"] if p.get("sizeFromManifest") else None
        if total is not None and total > MAX_FILE:
            raise WebInstallError(f"the file is over the {MAX_FILE / 1024**3:.0f} GB limit")
        if expected is not None and total is not None and total != expected:
            raise WebInstallError(f"the server says {total} bytes; the manifest says {expected}")
        digest = hashlib.sha256()
        done = 0
        while True:
            if cancelled and cancelled():
                raise Cancelled("download cancelled")
            try:
                chunk = r.read(CHUNK)
            except (OSError, http.client.HTTPException) as e:
                if cancelled and cancelled():
                    raise Cancelled("download cancelled")
                raise WebInstallError(f"download failed: {e}")
            if not chunk:
                if cancelled and cancelled():  # abort() makes the read end early
                    raise Cancelled("download cancelled")
                break
            done += len(chunk)
            if done > MAX_FILE:
                raise WebInstallError(f"the file is over the {MAX_FILE / 1024**3:.0f} GB limit")
            digest.update(chunk)
            out.write(chunk)
            if progress:
                progress(done, total or expected)
        out.close()
        if total is not None and done != total:
            raise WebInstallError(f"download cut off at {done} of {total} bytes")
        if expected is not None and done != expected:
            raise WebInstallError(f"downloaded {done} bytes; the manifest says {expected}")
        if p["sha256"] and digest.hexdigest() != p["sha256"]:
            raise WebInstallError(f"{p['file']} doesn't match the manifest's sha256; not installing it")
        os.replace(part, dest)
        ok = True
        return dest
    finally:
        out.close()
        conn.close()
        if not ok:
            try:
                os.remove(part)
            except OSError:
                pass


# ---- installing -------------------------------------------------------------

def dispatch(path, name=None, exe=None, progress=None, source=None):
    """Install a downloaded file with the installer for its type; returns {"message", "kind", "result"}.

    .apk goes to frame_android (its own Lepton instance and Steam shortcut, named by
    the APK's label); .zip and .exe to frame_titles. The caller has the SSH
    connection ready.
    """
    kind = file_kind(os.path.basename(path))
    if kind == "apk":
        import frame_android
        try:
            m = frame_android.install(path, source=source or os.path.basename(path))
        except frame_android.FrameError as e:
            raise WebInstallError(str(e))
        return {"message": f"Installed {m['label']} as its own app in the Steam library", "kind": kind, "result": m}
    try:
        import frame_titles
    except ImportError as e:
        if e.name != "frame_titles":
            raise
        raise WebInstallError("Linux/Windows titles need a newer Frame Control")
    result = frame_titles.install(path, name=name, exe=exe, progress=progress)
    msg = result.get("message") if isinstance(result, dict) else None
    return {"message": msg or f"Installed {name or os.path.basename(path)}", "kind": kind, "result": result}
