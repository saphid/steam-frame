// Downloads the official Windows embeddable Python into build/python-win, which
// the Windows build bundles as resources/python (so Windows users need no Python).
// Pinned by version and SHA-256. Run: node build/fetch-python.js
const crypto = require("crypto");
const fs = require("fs");
const https = require("https");
const path = require("path");
const { execFileSync } = require("child_process");

const VERSION = "3.12.10";
const SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3";
const URL = `https://www.python.org/ftp/python/${VERSION}/python-${VERSION}-embed-amd64.zip`;
const OUT = path.join(__dirname, "python-win");

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        return resolve(get(res.headers.location));
      }
      if (res.statusCode !== 200) return reject(new Error(`${url}: HTTP ${res.statusCode}`));
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => resolve(Buffer.concat(chunks)));
    }).on("error", reject);
  });
}

(async () => {
  const stamp = path.join(OUT, ".version");
  if (fs.existsSync(path.join(OUT, "python.exe")) && fs.existsSync(stamp) && fs.readFileSync(stamp, "utf8") === VERSION) {
    console.log(`Python ${VERSION} already in ${OUT}`);
    return;
  }
  const zip = await get(URL);
  const sum = crypto.createHash("sha256").update(zip).digest("hex");
  if (sum !== SHA256) throw new Error(`checksum mismatch for ${URL}: ${sum}`);
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, "python.zip");
  fs.writeFileSync(file, zip);
  // bsdtar (macOS, Windows 10+) reads zip files; GNU tar doesn't, so fall back to unzip.
  try { execFileSync("tar", ["-xf", file, "-C", OUT]); }
  catch { execFileSync("unzip", ["-q", "-o", file, "-d", OUT]); }
  fs.rmSync(file);
  fs.writeFileSync(path.join(OUT, ".version"), VERSION);
  console.log(`Python ${VERSION} -> ${OUT}`);
})().catch((e) => { console.error(e.message); process.exit(1); });
