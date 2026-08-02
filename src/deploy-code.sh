#!/usr/bin/env bash
# Deploy the Worker straight from this machine, bypassing git.
#
# The normal path is `git push`: Workers Builds then deploys what is actually in
# the repository. This script exists for the two cases that path cannot cover —
# GitHub or Builds being down, and testing a change without committing it.
#
# Cloudflare has no setting that restricts deploys to a branch, so nothing here
# can enforce the rule; this only makes the bypass deliberate rather than
# reflexive. Whatever it uploads exists nowhere but this machine until you
# commit it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

dirty="$(git status --porcelain)"
ahead="$(git log --oneline origin/main..HEAD 2>/dev/null || true)"

if [[ -n "$dirty" || -n "$ahead" ]]; then
  echo "This would publish code that is not in origin/main:" >&2
  [[ -n "$dirty" ]] && { echo "  uncommitted:" >&2; printf '%s\n' "$dirty" | sed 's/^/    /' >&2; }
  [[ -n "$ahead" ]] && { echo "  unpushed:" >&2; printf '%s\n' "$ahead" | sed 's/^/    /' >&2; }
  echo >&2
  echo "Push instead — Builds deploys it in about half a minute:" >&2
  echo "  git push origin main" >&2
  echo >&2
  read -r -p "Deploy from this machine anyway? [y/N] " reply
  [[ "$reply" == [yY] ]] || { echo "Cancelled." >&2; exit 1; }
fi

npx --yes wrangler deploy
