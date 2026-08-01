#!/usr/bin/env bash
# Publish data.json to the Worker's KV store.
#
# The value is overwritten in place, so no public snapshot of an earlier payload
# survives — unlike a Pages deploy, which kept every past upload at its own
# permanent URL. First run needs an authenticated CLI:
#
#   npx wrangler login
#   ./src/deploy-data.sh
set -euo pipefail

# data.json lives in the project root, one level up from this script.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$ROOT/data.json" ]]; then
  echo "data.json missing — run: python3 src/generate.py" >&2
  exit 1
fi

# --remote is what makes this hit the real namespace; without it wrangler
# writes to a local simulation and reports success while the dashboard sees
# nothing.
npx --yes wrangler kv key put payload \
  --path "$ROOT/data.json" \
  --binding DATA \
  --remote \
  --config "$ROOT/wrangler.toml"

echo
echo "Dashboard: https://career.omnilab.workers.dev/"
