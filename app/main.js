// Frame Control as a Mac app: starts ui/server.py on a free loopback port and
// shows it in a native window. The server does all the work over the `frame`
// SSH alias; this file only hosts it.
const { app, BrowserWindow, Menu, dialog, shell } = require("electron");
const { execFile, spawn } = require("child_process");
const { promisify } = require("util");
const fs = require("fs");
const http = require("http");
const net = require("net");
const os = require("os");
const path = require("path");

const run = promisify(execFile);

// Packaged: Contents/Resources/{ui,scripts}. Dev: the repo checkout.
const ROOT = app.isPackaged ? process.resourcesPath : path.join(__dirname, "..");
const SERVER = path.join(ROOT, "ui", "server.py");
const SCRIPTS = path.join(ROOT, "scripts");
const LOG_DIR = path.join(os.homedir(), "Library", "Logs", "Frame Control");
const LOG = path.join(LOG_DIR, "server.log");
const BG = "#0d1117";
const FRAME = process.env.FRAME_ALIAS || "frame";

let server = null;
let url = null;
let win = null;
let quitting = false;

// Apps launched from Finder get PATH=/usr/bin:/bin:/usr/sbin:/sbin, which misses
// Homebrew's python3, rsync and adb. Take PATH from the login shell instead.
// Runs asynchronously so a slow shell profile can't freeze the window.
let cachedPath = null;
async function loginPath() {
  if (cachedPath) return cachedPath;
  const shellPath = os.userInfo().shell || process.env.SHELL || "/bin/zsh";
  const extra = ["/opt/homebrew/bin", "/usr/local/bin", path.join(os.homedir(), ".homebrew", "bin")];
  let fromShell = "";
  try {
    const { stdout } = await run(shellPath, ["-ilc", 'printf "\\n__PATH__%s__PATH__" "$PATH"'],
                                 { encoding: "utf8", timeout: 5000 });
    fromShell = (stdout.match(/__PATH__(.*)__PATH__/) || [])[1] || "";
  } catch {}
  const parts = [...fromShell.split(":"), ...(process.env.PATH || "").split(":"), ...extra];
  const joined = [...new Set(parts.filter(Boolean))].join(":");
  if (fromShell) cachedPath = joined;  // retry next time if the shell didn't answer
  return joined;
}

async function findPython(env) {
  for (const dir of env.PATH.split(":")) {
    const p = path.join(dir, "python3");
    try {
      fs.accessSync(p, fs.constants.X_OK);
      // /usr/bin/python3 is a stub until the Command Line Tools are installed.
      await run(p, ["-c", "import http.server"], { timeout: 10000, env });
      return p;
    } catch {}
  }
  return null;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once("error", reject);
    s.listen(0, "127.0.0.1", () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

// Ready once the port answers with our Server header.
function ping(target) {
  return new Promise((resolve) => {
    const req = http.get(target, { timeout: 1000 }, (res) => {
      res.resume();
      resolve(/^FrameControl/.test(res.headers.server || ""));
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => { req.destroy(); resolve(false); });
  });
}

async function startServer() {
  const env = { ...process.env, PATH: await loginPath(), PYTHONUNBUFFERED: "1", PYTHONDONTWRITEBYTECODE: "1" };
  const python = await findPython(env);
  if (!python) {
    throw new Error("Frame Control needs python3. Install the Xcode Command Line Tools "
                    + "(xcode-select --install) or Homebrew's python, then reopen the app.");
  }
  const port = await freePort();
  fs.mkdirSync(LOG_DIR, { recursive: true });
  const log = fs.openSync(LOG, "a");
  fs.writeSync(log, `\n--- ${new Date().toISOString()} ${python} ${SERVER} --port ${port}\n`);
  const child = spawn(python, [SERVER, "--port", String(port)], { env, stdio: ["ignore", log, log] });
  fs.closeSync(log);
  server = child;
  let exited = null;
  child.once("error", (err) => {
    exited = err.message;
    if (server === child) { server = null; if (!quitting && url) serverDied(err.message); }
  });
  child.once("exit", (code, signal) => {
    exited = signal || code;
    if (server !== child) return;  // replaced by Restart Server
    server = null;
    if (!quitting && url) serverDied(exited);
  });

  const target = `http://127.0.0.1:${port}/`;
  for (let i = 0; i < 100; i++) {
    if (exited !== null) throw new Error(`The server exited (${exited}). See ${LOG}.`);
    if (await ping(target)) { url = target; return; }
    await new Promise((r) => setTimeout(r, 100));
  }
  if (server === child) server = null;
  child.kill("SIGTERM");
  throw new Error(`The server didn't start within 10 seconds. See ${LOG}.`);
}

function stopServer() {
  // server.py handles SIGTERM by closing its shared SSH connection.
  if (server) server.kill("SIGTERM");
}

function errorPage(message) {
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const html = `<!doctype html><meta charset="utf-8"><body style="margin:0;height:100vh;display:grid;
    place-items:center;background:${BG};color:#e6edf3;font:14px -apple-system,sans-serif">
    <div style="max-width:560px;padding:32px;line-height:1.5"><h2>Frame Control couldn't start</h2>
    <p>${esc(message)}</p><p style="color:#8b98a8">Fix it, then choose Frame → Restart Server.</p></div>`;
  return "data:text/html;charset=utf-8," + encodeURIComponent(html);
}

function serverDied(why) {
  url = null;
  if (win) win.loadURL(errorPage(`The server stopped unexpectedly (${why}). See ${LOG}.`));
}

async function restartServer() {
  const old = server;
  server = null;
  url = null;
  if (old) old.kill("SIGTERM");
  await load();
}

// The page's sticky header becomes the title bar, clear of the traffic lights.
const CHROME_CSS = `
  header { padding-left: 92px !important; -webkit-app-region: drag; user-select: none; }
  header a, header button, header input, header .chip { -webkit-app-region: no-drag; }
`;

// Restart Server can start a new load while an older one is still waiting for
// its server; only the newest load may touch the window.
let loadGen = 0;
async function load() {
  const gen = ++loadGen;
  try {
    if (!url) await startServer();
    if (gen === loadGen && win) { await win.loadURL(url); firstRunCheck(); }
  } catch (e) {
    if (gen === loadGen && win) await win.loadURL(errorPage(e.message));
  }
}

// `ssh -G` prints the effective config. An alias nobody configured keeps its
// own name as HostName; connect.sh always writes a HostName.
async function aliasConfigured(env) {
  try {
    const { stdout } = await run("ssh", ["-G", FRAME], { encoding: "utf8", timeout: 5000, env });
    return (stdout.match(/^hostname (.*)$/m) || [])[1] !== FRAME;
  } catch {
    return true;  // can't tell; don't nag
  }
}

let setupOffered = false;
async function firstRunCheck() {
  if (setupOffered || !url) return;  // not on the error page, and once per launch
  if (await aliasConfigured({ ...process.env, PATH: await loginPath() })) return;
  if (!win || setupOffered) return;
  setupOffered = true;
  const { response } = await dialog.showMessageBox(win, {
    type: "info",
    message: "Connect to your Steam Frame",
    detail: `There's no "${FRAME}" SSH alias yet. On the Frame, turn on Steam Settings → System → `
          + "Enable Developer Mode, then Developer → Set User Password. Then run the setup script: it finds the "
          + "headset, creates a key, and asks for that password once in Terminal.",
    buttons: ["Set Up Connection…", "Later"],
    defaultId: 0, cancelId: 1,
  });
  if (response === 0) setUpConnection();
}

function createWindow() {
  win = new BrowserWindow({
    width: 1400, height: 950, minWidth: 760, minHeight: 560,
    title: "Frame Control", backgroundColor: BG, show: false,
    titleBarStyle: "hiddenInset", trafficLightPosition: { x: 18, y: 26 },
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.once("ready-to-show", () => win.show());
  win.webContents.on("did-finish-load", () => win.webContents.insertCSS(CHROME_CSS));
  // External links open in the default browser; the app never navigates away.
  win.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:\/\//.test(target)) shell.openExternal(target);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, target) => {
    if (!url || new URL(target).origin !== new URL(url).origin) e.preventDefault();
  });
  win.on("closed", () => { win = null; });
  load();
}

// Runs in Terminal because ssh-copy-id asks for the Developer Mode password.
function runInTerminal(command) {
  const quoted = command.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  execFile("osascript", ["-e", 'tell application "Terminal"', "-e", `do script "${quoted}"`,
                         "-e", "activate", "-e", "end tell"], (err) => {
    if (err) dialog.showErrorBox("Couldn't open Terminal", String(err.message || err));
  });
}

const sh = (s) => `'${s.replace(/'/g, "'\\''")}'`;

function setUpConnection() {
  runInTerminal(`env ${sh(`FRAME_ALIAS=${FRAME}`)} zsh ${sh(path.join(SCRIPTS, "connect.sh"))}`);
}

function buildMenu() {
  const template = [
    { role: "appMenu" },
    { role: "fileMenu" },
    { role: "editMenu" },
    {
      label: "Frame",
      submenu: [
        { label: "Set Up Connection…", click: setUpConnection },
        { label: "Open SSH in Terminal", click: () => runInTerminal(`ssh ${sh(FRAME)}`) },
        { type: "separator" },
        { label: "Open in Browser", click: () => url && shell.openExternal(url) },
        { label: "Restart Server", click: () => win ? restartServer() : createWindow() },
        { label: "Show Server Log", click: () => shell.openPath(fs.existsSync(LOG) ? LOG : LOG_DIR) },
        { label: "Reveal Helper Scripts", click: () => shell.openPath(SCRIPTS) },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" }, { role: "forceReload" }, { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" },
        { type: "separator" }, { role: "togglefullscreen" },
      ],
    },
    { role: "windowMenu" },
    {
      role: "help",
      submenu: [{ label: "Project on GitHub", click: () => shell.openExternal("https://github.com/saphid/steam-frame") }],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
  });
  app.whenReady().then(() => {
    buildMenu();
    createWindow();
  });
  app.on("activate", () => { if (!win) createWindow(); });
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", () => { quitting = true; stopServer(); });
  process.on("exit", stopServer);
}
