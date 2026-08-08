# Career dashboard — conventions

## Layout

```
app/         → static files the Worker serves. Public: put nothing here that isn't.
src/         → the Worker, the generator, the vault validators, the two deploy scripts.
tests/       → test_validators.py — the fixture suite behind the validators.
payload.json → generated, gitignored, pushed to KV rather than committed.
```

`python3 tests/test_validators.py` builds one valid fixture per entity plus one
per defect, each the valid base with a single mutation, and asserts both the
expected message and the violation count — a defect caught by the wrong rule
fails. Run it after touching a validator: the vault sweep passing proves
nothing on its own, since a rule that stopped firing also passes.

Inside `src/`, `vault_schema.py` is the single definition of the vault's shape —
every enum, the frontmatter parser, the heading walker. Both halves import it:
`generate.py`, which trusts the vault, and `validate*.py`, which prove it. A
second copy of an enum anywhere else is the drift this split exists to prevent.

Only `app/` is reachable from the browser: the Worker serves that directory
through its `ASSETS` binding and answers `/payload.json` itself, so nothing
under `src/` is addressable. `wrangler.toml` is what defines this — a file
moved out of `app/` stops being public.

## Data flow

```
Obsidian vault → src/validate.py → src/generate.py → payload.json → src/deploy-data.sh → KV key "payload"
                    (gate)                                                                  ↓
                                                  career.omnilab.workers.dev/  →  /payload.json
```

`validate.py` runs before the generator, on the files a write just touched
(`python3 src/validate.py "<file>"`) or over the whole vault (no arguments), and
exits non-zero on any schema violation. It is a gate, not a report: the vault
has no version control and no undo, so the cheapest place to catch a malformed
note is the moment it is written, not the month later when a dashboard row is
missing.

One payload, one name at every hop: the file on disk, the KV key it is pushed
to, and the route it is served on all read `payload`.

Obsidian is the only source of truth. `payload.json` is derived and disposable —
regenerate it rather than editing it, and never commit it.

The dashboard and its data share one origin, so `app/index.html` just fetches
`/payload.json` — no CORS, no feed URL to configure per device. It renders the
`localStorage` copy first, then refreshes; a failed refresh keeps the cached
view and says so. That cache is the only offline path — a first visit on a
device with no network has nothing to show.

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
  `career-dashboard-local` runs `wrangler dev` against a local KV copy. Both are
  defined in `src/career.zsh` (sourced from `~/.zshrc`), so the commands are
  versioned with the pipeline they drive.

## First-time setup, per machine

```bash
npx wrangler login
```

## Privacy

`payload.json` carries company names, salary asks and interview feedback. Two
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
