#!/usr/bin/env bash
# Publish data.json to a personal Cloudflare Pages project.
#
# The dashboard itself is hosted separately and shared; this deploys only the
# data feed, into the account of whoever runs it. First run:
#
#   npx wrangler login
#   ./deploy-data.sh
#
# The project name doubles as the hostname, so pick something unguessable —
# the feed is reachable by anyone who has the URL.
set -euo pipefail

# data.json lives in the project root, one level up from this script.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${CAREER_DATA_PROJECT:-}"

if [[ -z "$PROJECT" ]]; then
  echo "Set CAREER_DATA_PROJECT to your Pages project name, e.g." >&2
  echo "  export CAREER_DATA_PROJECT=career-data-8f3kd92m" >&2
  exit 1
fi

if [[ ! -f "$ROOT/data.json" ]]; then
  echo "data.json missing — run: python3 src/generate.py" >&2
  exit 1
fi

# First run in a fresh account: the project has to exist before assets upload.
if ! npx --yes wrangler pages project list 2>/dev/null | grep -q "$PROJECT"; then
  echo "Creating Pages project $PROJECT ..."
  npx --yes wrangler pages project create "$PROJECT" --production-branch main
fi

# Ship a directory containing only the feed, so nothing else is ever published.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp "$ROOT/data.json" "$STAGE/data.json"

npx --yes wrangler pages deploy "$STAGE" \
  --project-name "$PROJECT" \
  --branch main \
  --commit-dirty=true

echo
echo "Feed:      https://${PROJECT}.pages.dev/data.json"
echo "Dashboard: <dashboard-url>/?data=https://${PROJECT}.pages.dev/data.json"
