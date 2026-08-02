# Career dashboard — conventions

## Layout

```
app/      → static files the Worker serves. Public: put nothing here that isn't.
src/      → the Worker, the generator, the two deploy scripts.
data.json → generated, gitignored, pushed to KV rather than committed.
```

Only `app/` is reachable from the browser: the Worker serves that directory
through its `ASSETS` binding and answers `/payload.json` itself, so nothing
under `src/` is addressable. `wrangler.toml` is what defines this — a file
moved out of `app/` stops being public.

## Data flow

```
Obsidian vault → src/generate.py → data.json → src/deploy-data.sh → KV key "payload"
                                                                      ↓
                          career.omnilab.workers.dev/  →  /payload.json
```

Obsidian is the only source of truth. `data.json` is derived and disposable —
regenerate it rather than editing it, and never commit it.

The dashboard and its data share one origin, so `app/index.html` just fetches
`/payload.json` — no CORS, no feed URL to configure per device. It renders the
`localStorage` copy first, then refreshes; a failed refresh keeps the cached
view and says so. A manual file picker stays as an offline fallback.

## Live URL

`https://career.omnilab.workers.dev` — dashboard and feed, behind Cloudflare
Access.

## Deploying

- **Dashboard code** — `git push`; Workers Builds deploys it in about half a
  minute. To publish from this machine instead, use `./src/deploy-code.sh`
  rather than bare `wrangler deploy`: it refuses, unless overridden, to ship
  code that is not in `origin/main`, so the live Worker never runs something
  that exists nowhere else.
- **Data** — `./src/deploy-data.sh`, which overwrites the KV key in place.
- `job-record` runs generate + deploy-data after every vault write. Locally, the
  `career-dashboard` zsh function does the same and opens the hosted page;
  `career-dashboard-local` runs `wrangler dev` against a local KV copy.

## First-time setup, per machine

```bash
npx wrangler login
```

## Privacy

`data.json` carries company names, salary asks and interview feedback. Two
independent guards:

- **Cloudflare Access** in front of the Worker — one-time PIN to an allowlisted
  address. Enabled from Workers & Pages → career → Settings → Domains & Routes.
- **The Worker's own check** — `/payload.json` compares
  `Cf-Access-Authenticated-User-Email` against `OWNER` in `src/worker.js`, so
  adding someone to the Access allowlist does not hand them the data. Whoever
  else needs a dashboard gets their own Worker and KV key.

Access sets that header itself and strips any copy sent by the client, so it
cannot be forged. A request without it is refused rather than allowed: an
absent header means the request never passed through Access, and treating that
as acceptable would make the second guard depend on the first. The exception is
`localhost`, so `wrangler dev` still works.
