#!/usr/bin/env bash
# Publish payload.json to the Worker's KV store, overwriting the value in place so
# no public snapshot of an earlier payload survives. First run needs an
# authenticated CLI:
#
#   npx wrangler login
#   ./src/deploy-data.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$ROOT/payload.json" ]]; then
  echo "payload.json missing — run: python3 src/generate.py" >&2
  exit 1
fi

# --remote is what makes this hit the real namespace; without it wrangler
# writes to a local simulation and reports success while the dashboard sees
# nothing.
put_payload() {
  npx --yes wrangler kv key put payload \
    --path "$ROOT/payload.json" \
    --binding DATA \
    --remote \
    --config "$ROOT/wrangler.toml"
}

# One retry: a just-refreshed OAuth token takes a few seconds to propagate to
# the API, and the first write can land inside that window as a 401. A second
# failure is a real problem and stops the script with wrangler's own error.
if ! put_payload; then
  echo "First put failed — retrying in 3s..." >&2
  sleep 3
  put_payload
fi

echo
echo "Dashboard: https://career.omnilab.workers.dev/"
