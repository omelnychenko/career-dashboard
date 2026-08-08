# The `career-dashboard` shell functions, kept in the repo so the daily flow is
# versioned with the pipeline it drives. Applied by sourcing it from ~/.zshrc:
#
#   source /Users/omelnychenko/Projects/Personal/AI/career-dashboard/src/career.zsh

# Resolved from this file's own location, so a second person's checkout works
# wherever they put it.
CAREER_ROOT="${${(%):-%x}:A:h:h}"
CAREER_URL="https://career.omnilab.workers.dev/"

# Rebuild the data, push it to KV, open the hosted dashboard (run from any folder).
# The vault is validated first and a violation stops the chain: publishing a
# payload built from a malformed note hides the problem behind a page that looks
# fine, and the vault has no undo to walk it back with.
career-dashboard() {
    (
        cd "$CAREER_ROOT" \
            && python3 src/validate.py \
            && python3 src/generate.py \
            && ./src/deploy-data.sh \
            && open "$CAREER_URL"
    )
}

# Run the whole thing locally — wrangler serves app/ and a local KV copy, so the
# dashboard finds /payload.json at the same origin exactly as in production.
career-dashboard-local() {
    (
        cd "$CAREER_ROOT" \
            && python3 src/validate.py \
            && python3 src/generate.py \
            && npx --yes wrangler kv key put payload --path payload.json --binding DATA \
            && npx --yes wrangler dev
    )
}
