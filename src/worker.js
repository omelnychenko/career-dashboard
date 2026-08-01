// Serves the dashboard and its data from one origin: static files from app/,
// the payload from KV. Everything here sits behind Cloudflare Access.

// Access lets through everyone on the application's allowlist. The dashboard
// carries salary asks and interview feedback, so the payload additionally
// checks who is asking — adding someone to the allowlist for another Worker
// must not hand them this data.
const OWNER = "oleksii.melnychenko@gmail.com";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname !== "/payload.json") {
      return env.ASSETS.fetch(request);
    }

    // Set by Access on every authenticated request, and stripped from incoming
    // requests by Cloudflare, so it cannot be spoofed by the client. Absent
    // when Access is not yet enabled in front of this Worker.
    const email = request.headers.get("cf-access-authenticated-user-email");
    if (email && email.toLowerCase() !== OWNER) {
      return new Response("Not your data.", { status: 403 });
    }

    const body = await env.DATA.get("payload", "stream");
    if (!body) {
      return new Response(JSON.stringify({ error: "no data yet" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      });
    }

    return new Response(body, {
      headers: {
        "content-type": "application/json; charset=utf-8",
        // The payload is rewritten in place on every deploy, so a cached copy
        // is a stale copy.
        "cache-control": "no-store",
      },
    });
  },
};
