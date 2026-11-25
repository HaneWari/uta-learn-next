/**
 * Anonymous heartbeat endpoint for Uta Learn Next.
 *
 * POST /v1/ping  { "iid": uuid-v4, "v": "2.0.0", "os": "win10|win11|other" }
 *   → 204 on success, 400 on anything malformed.
 *
 * What this worker deliberately does NOT do: read the IP, read User-Agent,
 * geolocate, store a timestamp finer than a day, or log requests. The three
 * fields are the entire payload, and the table has columns for exactly those
 * three plus the day. The code is here so users can verify that claim.
 */
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SEMVER = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;
const OS = new Set(["win10", "win11", "other"]);
const MAX_BODY = 256;

const headers = {
  // no CORS: this endpoint is called by the Python client, not a browser
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "POST" || url.pathname !== "/v1/ping") {
      return new Response(JSON.stringify({ error: "not found" }), {
        status: 404,
        headers,
      });
    }

    const raw = await request.text();
    if (raw.length > MAX_BODY) {
      return bad("body too large");
    }

    let body;
    try {
      body = JSON.parse(raw);
    } catch {
      return bad("invalid json");
    }
    if (typeof body !== "object" || body === null) return bad("invalid body");

    const { iid, v, os } = body;
    if (typeof iid !== "string" || !UUID_V4.test(iid)) return bad("bad iid");
    if (typeof v !== "string" || v.length > 32 || !SEMVER.test(v)) {
      return bad("bad version");
    }
    if (typeof os !== "string" || !OS.has(os)) return bad("bad os");

    const day = new Date().toISOString().slice(0, 10);
    try {
      await env.DB.prepare(
        "INSERT OR IGNORE INTO pings (iid, day, v, os) VALUES (?, ?, ?, ?)",
      )
        .bind(iid, day, v, os)
        .run();
    } catch {
      // a broken DB must not make the client retry all day
      return new Response(null, { status: 204, headers });
    }
    return new Response(null, { status: 204, headers });
  },
};

function bad(reason) {
  return new Response(JSON.stringify({ error: reason }), {
    status: 400,
    headers,
  });
}
