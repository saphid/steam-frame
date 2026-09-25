import { capsule, endpoint, json, string, table, text } from "lakebed/server";

// Compatibility reports for Android apps on the Steam Frame, written and read
// only by Frame Control. There are no queries or mutations, so browsers and
// Lakebed clients can't reach the data; the two endpoints require the app key
// (FRAME_CONTROL_KEY in .env.lakebed.server, kept in the Mac's Keychain).

const RESULTS = ["runs", "crashes", "install_failed", "instance_failed"];
const RATINGS = ["works", "issues", "broken"];
const PAGE = 500;

type Incoming = Record<string, unknown>;

function field(r: Incoming, key: string, max = 200): string | undefined {
  const v = r[key];
  if (v === undefined || v === null || v === "") return undefined;
  return String(v).slice(0, max);
}

function authorised(ctx: { env: Record<string, string | undefined> }, key: string | null): boolean {
  const expected = ctx.env.FRAME_CONTROL_KEY;
  if (!expected || !key) return false;
  // Compare every position of the longer string so timing doesn't reveal the key length.
  const n = Math.max(key.length, expected.length);
  let diff = key.length ^ expected.length;
  for (let i = 0; i < n; i++) diff |= (key.charCodeAt(i) || 0) ^ (expected.charCodeAt(i) || 0);
  return diff === 0;
}

export default capsule({
  name: "frame-compat",

  auth: { requireSignIn: false },

  schema: {
    reports: table({
      package: string(),
      version: string().optional(),
      result: string().optional(),
      rating: string().optional(),
      notes: string().optional(),
      via: string().optional(),
      reportedAt: string(),
      steamos: string().optional(),
      lepton: string().optional(),
      runtime: string().optional(),
      label: string().optional(),
      source: string().optional(),
      clientId: string()
    }).index("by_package", ["package"]).index("by_client", ["clientId"])
  },

  endpoints: {
    // GET /v1/reports?since=<createdAt>  -> { reports: [...], next: <createdAt> | null }
    // Pass `next` back as `since` until it's null; rows at the boundary repeat, so dedupe by id.
    list: endpoint({ method: "GET", path: "/v1/reports" }, async (ctx, req) => {
      if (!authorised(ctx, req.headers.get("x-frame-control-key"))) return text("unauthorized", { status: 401 });
      const since = req.query.get("since") ?? "";
      const rows = await ctx.db.reports
        .withIndex("by_creation", (q) => q.gte("createdAt", since))
        .take(PAGE);
      return json({ reports: rows, next: rows.length === PAGE ? rows[rows.length - 1].createdAt : null });
    }),

    // POST /v1/reports  body: { reports: [ {...}, ... ] }  (max 100 per call)
    // clientId makes retries idempotent: a report already stored is skipped.
    // Invalid reports are listed in `rejected` (by clientId) so the app can keep them.
    add: endpoint({ method: "POST", path: "/v1/reports" }, async (ctx, req) => {
      if (!authorised(ctx, req.headers.get("x-frame-control-key"))) return text("unauthorized", { status: 401 });
      const body = await req.json<{ reports?: Incoming[] }>();
      const incoming = Array.isArray(body?.reports) ? body.reports.slice(0, 100) : [];
      let inserted = 0;
      const rejected: string[] = [];
      for (const r of incoming) {
        const pkg = field(r, "package");
        const clientId = field(r, "clientId", 80);
        const reportedAt = field(r, "date", 40);
        const result = field(r, "result");
        const rating = field(r, "rating");
        if (!pkg || !clientId || !reportedAt || (result && !RESULTS.includes(result)) ||
            (rating && !RATINGS.includes(rating))) {
          if (clientId) rejected.push(clientId);
          continue;
        }
        const dup = await ctx.db.reports.withIndex("by_client", (q) => q.eq("clientId", clientId)).first();
        if (dup) continue;
        await ctx.db.reports.insert({
          package: pkg, version: field(r, "version", 80), result, rating,
          notes: field(r, "notes", 1000), via: field(r, "via", 20), reportedAt,
          steamos: field(r, "steamos", 40), lepton: field(r, "lepton", 40),
          runtime: field(r, "runtime", 20), label: field(r, "label", 120),
          source: field(r, "source", 300), clientId
        });
        inserted++;
      }
      return json({ inserted, rejected, received: incoming.length });
    }),

    status: endpoint({ method: "GET", path: "/v1/status" }, () => text("ok"))
  }
});
