// Parses frame-control://install?manifest=URL and frame-control://install?url=URL
// (see docs/web-install.md). Pure, so it runs under plain node for the tests.
// This is only a first filter: ui/frame_webinstall.py applies the full URL rules
// (HTTPS, no private addresses, redirects) before anything is fetched.
const SCHEME = "frame-control";
const MAX_LINK = 4096;
const MAX_URL = 2048;

// {kind: "manifest" | "url", target} or null if raw isn't a usable install link.
function parseInstallLink(raw) {
  if (typeof raw !== "string" || raw.length > MAX_LINK || !raw.toLowerCase().startsWith(`${SCHEME}:`)) return null;
  let link;
  try { link = new URL(raw); } catch { return null; }
  // frame-control://install?… puts "install" in the host; accept a trailing slash too.
  if (link.protocol !== `${SCHEME}:` || link.hostname !== "install" || !["", "/"].includes(link.pathname)) return null;
  const keys = [...new Set(link.searchParams.keys())];
  if (keys.length !== 1 || !["manifest", "url"].includes(keys[0])) return null;
  const values = link.searchParams.getAll(keys[0]);
  if (values.length !== 1) return null;
  const target = values[0];
  if (!target || target.length > MAX_URL) return null;
  let parsed;
  try { parsed = new URL(target); } catch { return null; }
  if (!["https:", "http:"].includes(parsed.protocol) || parsed.username || parsed.password) return null;
  return { kind: keys[0], target };
}

// The link among command-line arguments (Windows and Linux pass it there).
function linkFromArgv(argv) {
  return (argv || []).find((a) => typeof a === "string" && a.toLowerCase().startsWith(`${SCHEME}:`)) || null;
}

module.exports = { SCHEME, parseInstallLink, linkFromArgv };
