#!/usr/bin/env bash
# posts a sticky comment on pr $PR with the overall score, compared against
# the base branch's, and a link to the workflow run summary. a hidden marker
# keyed by $KEY finds the previous comment, which is updated in place.
#
# comment.sh [-n|--dry-run]: with it, prints the comment body and posts
# nothing; GH_TOKEN and PR are then not needed.
#
# env: GH_TOKEN, KEY, PR, BASE_REF, OVERALL and BASE_OVERALL (may be empty),
# NAME (may be empty: what the comment says was evaluated), RUN_FAILED (`true`
# when the pats run failed), HEAD_SHA (may be empty: the commit this run is
# of, see below).
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

# ":green_circle: 0.76", same thresholds as the full report, or "n/a" when
# empty. $2 goes on both sides of the number.
fmt() {
  if [[ -z "$1" ]]; then echo "n/a"; return; fi
  awk -v s="$1" -v w="${2:-}" 'BEGIN {
    colour = s >= 0.8 ? "green" : s >= 0.5 ? "yellow" : "red"
    printf ":%s_circle: %s%.2f%s", colour, w, s, w
  }'
}

# the change against the base score, empty without both scores. a failed run
# says so instead: what it scored, if anything, is not a result to compare.
delta=""
if [[ "${RUN_FAILED:-}" == true ]]; then
  delta=" &middot; :x: **run failed**"
elif [[ -n "${OVERALL:-}" && -n "${BASE_OVERALL:-}" ]]; then
  d="$(awk -v h="$OVERALL" -v b="$BASE_OVERALL" 'BEGIN { printf "%+.2f", h - b }')"
  case "$d" in
    +0.00|-0.00) delta="no change" ;;
    +*)          delta=":chart_with_upwards_trend: **$d**" ;;
    *)           delta=":chart_with_downwards_trend: **$d**" ;;
  esac
  delta=" &middot; $delta"
fi

key="${KEY//[^A-Za-z0-9._\/-]/_}"  # ends up in a jq string literal below
name="${NAME:-}"
name="${name//[^A-Za-z0-9._-]/_}"
# the marker first. the scores read base to pr.
body="<!-- pats-comment:$key -->
### pats evaluation${name:+: \`$name\`}

\`$base\` $(fmt "${BASE_OVERALL:-}") &rarr; PR $(fmt "${OVERALL:-}" "**")$delta

[full report]($run_url): per-task scores, scorer breakdown and run stats."
if [[ "$dry" == 1 ]]; then
  printf '%s\n' "$body"
  exit 0
fi
marker="$(head -n1 <<< "$body")"
payload="$(jq -Rs '{body: .}' <<< "$body")"

id="$(gh api --paginate "repos/$repo/issues/$PR/comments" \
  --jq ".[] | select(.body | startswith(\"$marker\")) | .id" | tail -n1)"

# a run of a commit that is no longer the pr's head leaves the comment alone.
# finishing late, or re-run by hand, it would put an older score over the one
# of a newer run, or post a second comment next to it.
if [[ -n "${HEAD_SHA:-}" ]]; then
  if ! head="$(gh api "repos/$repo/pulls/$PR" --jq .head.sha)" || [[ -z "$head" ]]; then
    echo "::warning::could not read the pr head: commenting without that check"
  elif [[ "$head" != "$HEAD_SHA" ]]; then
    echo "::notice::the pr head moved from ${HEAD_SHA:0:7} to ${head:0:7}: comment left alone"
    exit 0
  fi
fi
if [[ -n "$id" ]]; then
  gh api -X PATCH "repos/$repo/issues/comments/$id" --input - --jq .html_url <<< "$payload"
else
  gh api -X POST "repos/$repo/issues/$PR/comments" --input - --jq .html_url <<< "$payload"
fi
