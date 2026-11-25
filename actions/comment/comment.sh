#!/usr/bin/env bash
# posts a sticky comment on pr $PR with the overall score, compared against
# the base branch's, and a link to the workflow run summary. a hidden marker
# keyed by $KEY finds the previous comment, which is updated in place.
#
# comment.sh [-n|--dry-run]: with it, prints the comment body and posts
# nothing; GH_TOKEN and PR are then not needed.
#
# env: GH_TOKEN, KEY, PR, BASE_REF, OVERALL and BASE_OVERALL (may be empty),
# NAME (may be empty: what the comment says was evaluated).
set -euo pipefail

dry=0
case "${1:-}" in
  "") ;;
  -n|--dry-run) dry=1 ;;
  *) echo "usage: comment.sh [-n|--dry-run]" >&2; exit 2 ;;
esac

: "${KEY:?}"
if [[ "$dry" == 0 ]]; then
  : "${GH_TOKEN:?}" "${PR:?not a pull_request event}"
fi
repo="$GITHUB_REPOSITORY"
run_url="$GITHUB_SERVER_URL/$repo/actions/runs/$GITHUB_RUN_ID"
base="${BASE_REF:-base}"
base="${base//[^A-Za-z0-9._\/-]/_}"  # shown in a code span

# "0.76", or "n/a" when empty.
fmt() {
  if [[ -z "$1" ]]; then echo "n/a"; return; fi
  awk -v s="$1" 'BEGIN { printf "%.2f", s }'
}

# " (+0.06)": the change against the base score. empty without both scores.
delta=""
if [[ -n "${OVERALL:-}" && -n "${BASE_OVERALL:-}" ]]; then
  delta="$(awk -v h="$OVERALL" -v b="$BASE_OVERALL" 'BEGIN { printf " (%+.2f)", h - b }')"
  delta="${delta/-0.00/+0.00}"
fi

key="${KEY//[^A-Za-z0-9._\/-]/_}"  # ends up in a jq string literal below
name="${NAME:-}"
name="${name//[^A-Za-z0-9._-]/_}"
title="pats evaluation${name:+: \`$name\`}"
# the marker, then one line: base score first, then the pr's.
body="<!-- pats-comment:$key -->
**$title** &middot; \`$base\` $(fmt "${BASE_OVERALL:-}") &rarr; PR **$(fmt "${OVERALL:-}")**$delta &middot; [full report]($run_url)"
if [[ "$dry" == 1 ]]; then
  printf '%s\n' "$body"
  exit 0
fi
marker="$(head -n1 <<< "$body")"
payload="$(jq -Rs '{body: .}' <<< "$body")"

id="$(gh api --paginate "repos/$repo/issues/$PR/comments" \
  --jq ".[] | select(.body | startswith(\"$marker\")) | .id" | tail -n1)"
if [[ -n "$id" ]]; then
  gh api -X PATCH "repos/$repo/issues/comments/$id" --input - --jq .html_url <<< "$payload"
else
  gh api -X POST "repos/$repo/issues/$PR/comments" --input - --jq .html_url <<< "$payload"
fi
