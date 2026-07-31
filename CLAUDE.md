# Career dashboard — conventions

## Layout

```
app/      → published to Cloudflare Pages. Public: put nothing here that isn't.
src/      → everything that runs locally and is never published.
data.json → generated, gitignored, deployed separately as its own feed.
```

A file goes in `app/` only if the world is meant to fetch it — the split is by
published-or-not, not by language. Cloudflare's build output directory is set to
`app` in the project's console settings; that, not `.gitignore`, is what keeps
`src/` private, so verify it there if anything under `src/` ever appears on the
public URL.

## Data flow

```
Obsidian vault → src/generate.py → data.json → src/deploy-data.sh → <feed>.pages.dev/data.json
                                                                      ↓
                              career-4u.pages.dev/?data=<feed-url>
```

Obsidian is the only source of truth. `data.json` is derived and disposable —
regenerate it rather than editing it, and never commit it.

`app/index.html` loads its data over the network from the `?data=` URL, pinning
it to `localStorage` on first visit so the bare dashboard URL works afterwards.
It renders the cached copy first, then refreshes; a failed refresh keeps the
cached view and says so. There is also a manual file picker as a fallback.

## Live URLs

- Dashboard: `https://career-4u.pages.dev` (git-deployed, output directory `app`)
- Owner's feed: `https://career-data-2ucgrsgthbpa.pages.dev/data.json`

## Deploying

- **Dashboard code** — `git push`; Cloudflare Pages builds from the repo
  (no build command, output directory `app`).
- **Data feed** — `./src/deploy-data.sh`, with `CAREER_DATA_PROJECT` set to the
  Pages project name. Ships only `data.json` from a temp directory, then deletes
  the superseded deployments.
- `job-record` runs generate + deploy-data after every vault write. Locally, the
  `career-dashboard` zsh function does the same and opens the hosted page;
  `career-dashboard-local` serves the repo on :8777 without deploying.

Each person publishes their own feed and opens the shared dashboard with their
own `?data=` URL, so no one needs access to anyone else's data.

## First-time setup, per person

```bash
npx wrangler login                                   # once, per machine
export CAREER_DATA_PROJECT=career-data-<random>      # add to ~/.zshrc
./src/deploy-data.sh                                 # creates the project, publishes
```

The project name becomes the hostname and is the only thing protecting the feed,
so make it random rather than guessable. Then open the dashboard once as
`<dashboard-url>/?data=<feed-url>`: the feed is pinned per device and the bare
URL works afterwards. **Clear data** unpins it.

## Privacy

`data.json` carries company names, salary asks and interview feedback. The feed
is currently protected only by an unguessable project name — treat the URL as a
secret. To close it properly, put Cloudflare Access in front of the *data*
project (Zero Trust → Access → Applications, free tier covers it); the
dashboard keeps working and no code changes.
