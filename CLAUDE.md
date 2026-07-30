# Career dashboard — conventions

## Layout

```
app/      → published to Cloudflare Pages. Public: put nothing here that isn't.
src/      → everything that runs locally and is never published.
data.json → generated, gitignored, deployed separately as its own feed.
```

The split is by *published or not* — not by language or by code-vs-script. A new
file goes in `app/` only if the world is meant to fetch it.

The split is the privacy mechanism: Cloudflare's build output directory is set
to `app`, so only what is inside it can reach the public URL. `.gitignore` does
not control this — it governs the repo, not the deploy. Never widen the output
directory to the repo root.

## Data flow

```
Obsidian vault → src/generate.py → data.json → src/deploy-data.sh → <feed>.pages.dev/data.json
                                                                      ↓
                              career-dashboard.pages.dev/?data=<feed-url>
```

Obsidian is the only source of truth. `data.json` is derived and disposable —
regenerate it rather than editing it, and never commit it.

`app/index.html` loads its data over the network from the `?data=` URL, pinning
it to `localStorage` on first visit so the bare dashboard URL works afterwards.
It renders the cached copy first, then refreshes; a failed refresh keeps the
cached view and says so. There is also a manual file picker as a fallback.

## Deploying

- **Dashboard code** — `git push`; Cloudflare Pages builds from the repo
  (no build command, output directory `app`).
- **Data feed** — `./src/deploy-data.sh`, with `CAREER_DATA_PROJECT` set to the
  Pages project name. Ships only `data.json`, from a temp directory.
- `job-record` runs generate + deploy-data after every vault write.

Each person publishes their own feed and opens the shared dashboard with their
own `?data=` URL, so no one needs access to anyone else's data.

## Privacy

`data.json` carries company names, salary asks and interview feedback. The feed
is currently protected only by an unguessable project name — treat the URL as a
secret. To close it properly, put Cloudflare Access in front of the *data*
project (Zero Trust → Access → Applications, free tier covers it); the
dashboard keeps working and no code changes.
