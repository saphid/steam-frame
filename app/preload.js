// Lets the page read this computer's clipboard through Electron, so sending it
// to the Frame needs no pbpaste, PowerShell, xclip or wl-clipboard.
// It also receives frame-control://install links (docs/web-install.md): only
// what the link asked for, never an install; the page asks the user first.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("frameApp", {
  readClipboard: () => ipcRenderer.invoke("clipboard:read"),
  onInstallLink: (cb) => {
    ipcRenderer.removeAllListeners("install-link");
    ipcRenderer.on("install-link", (_e, req) => cb({ kind: req.kind, target: req.target }));
    ipcRenderer.send("install-link:ready");
  },
});
