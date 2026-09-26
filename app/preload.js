// Lets the page read this computer's clipboard through Electron, so sending it
// to the Frame needs no pbpaste, PowerShell, xclip or wl-clipboard. Also tells
// the page where a dropped file or folder lives, so a folder can be sideloaded
// as a title without zipping it (the local server reads it from there).
const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("frameApp", {
  readClipboard: () => ipcRenderer.invoke("clipboard:read"),
  pathForFile: (file) => { try { return webUtils.getPathForFile(file) || ""; } catch { return ""; } },
});
