// Lets the page read this computer's clipboard through Electron, so sending it
// to the Frame needs no pbpaste, PowerShell, xclip or wl-clipboard.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("frameApp", {
  readClipboard: () => ipcRenderer.invoke("clipboard:read"),
});
