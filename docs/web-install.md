# Install links for websites

A website can put an "Install with Frame Control" button next to its download.
Clicking it opens Frame Control, which shows what the link wants to install and
asks the user. Only after they click **Install** does it download the file and
install it on the Frame.

What's verified: the link parsing, URL rules, manifest parsing, download,
size cap and sha256 check, by `tests/test_webinstall.py` and
`tests/test_server.py` (no network: a stub server on 127.0.0.1). Installing on
the headset is the same code as dropping a file on Frame Control: `.apk` files go
to the APK installer ([apks.md](apks.md)), `.zip` and `.exe` files to the
Linux/Windows title installer. A link hasn't been clicked through to a headset
install yet.

## The link

```
frame-control://install?manifest=<URL-encoded manifest URL>
frame-control://install?url=<URL-encoded file URL>
```

Use `manifest` when you can: it carries the title's name and a sha256, which
Frame Control checks before installing. `url` is for a file on its own; the
dialog then names the title after the file.

The manifest is FrameDrop's format, so one manifest serves both apps. The
schema may be `framedrop.install/v1` or `frame-control.install/v1`:

```json
{
  "schema": "framedrop.install/v1",
  "name": "My Game",
  "files": [
    { "url": "https://cdn.example.com/mygame-arm64.apk", "sha256": "optional-but-better" }
  ]
}
```

| Field | |
|---|---|
| `schema` | Required, one of the two above |
| `name` | Shown in the confirm dialog (at most 120 characters). Defaults to the file name. APKs are still named in the Steam library by their own label |
| `files` | Exactly one entry for now; more is refused with a message |
| `files[0].url` | Required. The file to install |
| `files[0].sha256` | Optional, 64 hex digits. The download must match or nothing is installed |
| `files[0].size` | Optional (Frame Control extension), bytes. Shown up front; the download must match |
| `files[0].exe` | Optional (Frame Control extension), for a `.zip` title: the program inside it to run |

What gets installed depends on the file name's extension:

| File | Installed as |
|---|---|
| `.apk` | An Android app in its own Lepton instance with a Steam shortcut ([apks.md](apks.md)) |
| `.zip`, `.exe` | A Linux or Windows title. Versions of Frame Control without the title installer say "Linux/Windows titles need a newer Frame Control" |
| anything else | Refused |

## Rules

Frame Control refuses a link, and downloads nothing, unless:

- Every URL (the manifest's, the file's and each redirect) is `https://`.
  `http://` works only for `localhost` or `127.0.0.1`, for testing: only when
  Frame Control runs with `FRAME_CONTROL_LOCAL_LINKS=1`, and only when the
  link itself points there. It's off by default so a website's link can't make
  the app fetch from services on your computer, and a public manifest can
  never send it there.
- No URL has a user name or password in it (`https://user:pw@…`).
- No host is, or resolves to, a private, loopback, link-local, CGNAT
  (100.64.0.0/10), multicast or otherwise non-public address. Every address
  the name has must be public, it's checked again on every redirect (at most
  5), and the download connects to the address that was checked.
- The file URL ends in a file name with one of the extensions above
  (`https://example.com/games/` is refused).
- The manifest is JSON of at most 256 KB, and the file at most 4 GiB
  (`MAX_MANIFEST` and `MAX_FILE` in `ui/frame_webinstall.py`).
- The user confirms. The dialog shows the title's name, the site the link came
  from (and the file's host if different), the file name and type, the size if
  known, and whether a sha256 was given.

A web page can't install anything itself: it can only open the link. Frame
Control's local server refuses requests from web pages, so the only way in is
the operating system handing the link to the app, then the user's click.

## Button for your site

Paste this where the download is, with your manifest's URL in `MANIFEST`:

```html
<a id="frame-control-install" href="#"
   style="display:inline-block;padding:10px 18px;border-radius:4px;background:#1a9fff;color:#fff;
          font:600 15px -apple-system,'Segoe UI',sans-serif;text-decoration:none">Install with Frame Control</a>
<script>
(() => {
  const MANIFEST = "https://example.com/mygame/frame-control.json";
  const GET_APP = "https://github.com/saphid/steam-frame/releases/latest";
  const button = document.getElementById("frame-control-install");
  button.href = "frame-control://install?manifest=" + encodeURIComponent(MANIFEST);
  button.addEventListener("click", () => {
    // If Frame Control opens, this page loses focus; if it doesn't, offer the download.
    let left = false;
    const away = () => { left = true; };
    window.addEventListener("blur", away, { once: true });
    setTimeout(() => {
      window.removeEventListener("blur", away);
      if (!left && confirm("Frame Control didn't open. Download it?")) location.href = GET_APP;
    }, 2000);
  });
})();
</script>
```

For a single file, use `"frame-control://install?url=" + encodeURIComponent(FILE_URL)`.

`docs/install.html` is a landing page that does the same from a plain link:
`install.html?manifest=<URL-encoded URL>` tries the app and shows a "Get Frame
Control" link. It isn't published anywhere yet; host a copy to use it.

## Testing locally

Start Frame Control with `FRAME_CONTROL_LOCAL_LINKS=1` in its environment (for
example `FRAME_CONTROL_LOCAL_LINKS=1 npm start` in `app/`), then serve the
manifest and file from your own computer:

```sh
cd mygame && python3 -m http.server 8000
open 'frame-control://install?manifest=http%3A%2F%2Flocalhost%3A8000%2Fmanifest.json'   # xdg-open on Linux, start "" on Windows
```

The manifest's file URL must then be `http://localhost:8000/…` or
`http://127.0.0.1:8000/…` too.

## How it works

- `app/install-link.js` parses the link (only `frame-control://install` with
  exactly one `manifest` or `url`); `app/main.js` registers the scheme
  (`app.setAsDefaultProtocolClient`, and electron-builder's `protocols` for the
  macOS Info.plist and the Linux `.desktop` file). macOS delivers links through
  `open-url`, Windows and Linux as an argument to a second instance. Links
  wait in the main process until the page has loaded and asked for them
  (`frameApp.onInstallLink` in `app/preload.js`). `framedrop://` is left alone.
- The page posts the link to `/api/webinstall/check`, which reads the manifest,
  applies the rules, asks the file's size with a HEAD request and returns a
  one-time id. Nothing is downloaded.
- **Install** posts the id to `/api/webinstall/start`. The server downloads to
  a temporary folder (progress at `/api/webinstall/job`, cancellable with
  `/api/webinstall/cancel`), checks size and sha256, hands the file to
  `frame_webinstall.dispatch()` and deletes the folder.
- The app registers the scheme each time it starts, so the last Frame Control
  started (e.g. a development checkout) handles the links.

**Quitting during a stalled download.** On macOS and Linux, quitting stops a
download at once (`shutdown()` on its socket wakes the blocked read). On
Windows that doesn't wake a read in another thread, and closing the handle
under a TLS read isn't safe, so a download that has stalled holds the quit for
the 4-second grace period until the app stops the server; the partial file is
removed on the next start. Downloads that are still moving stop at their next
read either way.
