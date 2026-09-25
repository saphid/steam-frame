// Renders build/icon.svg to icon.png (1024px) and icon.icns. Run: npm run icon
const { app, BrowserWindow } = require("electron");
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

app.dock?.hide();
app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: 1024, height: 1024, show: false, transparent: true, frame: false,
                                  useContentSize: true, webPreferences: { offscreen: true } });
  const svg = fs.readFileSync(path.join(__dirname, "icon.svg"), "utf8");
  await win.loadURL("data:text/html," + encodeURIComponent(
    `<body style="margin:0;background:transparent">${svg}</body>`));
  await new Promise((r) => setTimeout(r, 300));
  const png = (await win.webContents.capturePage({ x: 0, y: 0, width: 1024, height: 1024 }))
    .resize({ width: 1024, height: 1024 }).toPNG();
  fs.writeFileSync(path.join(__dirname, "icon.png"), png);

  const set = fs.mkdtempSync(path.join(os.tmpdir(), "icon-")) + "/icon.iconset";
  fs.mkdirSync(set);
  for (const size of [16, 32, 128, 256, 512]) {
    for (const scale of [1, 2]) {
      const px = size * scale, name = `icon_${size}x${size}${scale === 2 ? "@2x" : ""}.png`;
      execFileSync("sips", ["-z", String(px), String(px), path.join(__dirname, "icon.png"),
                            "--out", path.join(set, name)], { stdio: "ignore" });
    }
  }
  execFileSync("iconutil", ["-c", "icns", set, "-o", path.join(__dirname, "icon.icns")]);
  console.log("wrote build/icon.png and build/icon.icns");
  app.quit();
});
