#!/usr/bin/env bash
# posts a sticky comment on pr $PR with the overall score, compared against
# the base branch's, and a link to the workflow run summary. a hidden marker
# keyed by $KEY finds the previous comment, which is updated in place.
#
# env: GH_TOKEN, KEY, PR, BASE_REF, OVERALL and BASE_OVERALL (may be empty).
set -euo pipefail

: "${GH_TOKEN:?}" "${KEY:?}" "${PR:?not a pull_request event}"
repo="$GITHUB_REPOSITORY"
run_url="$GITHUB_SERVER_URL/$repo/actions/runs/$GITHUB_RUN_ID"

# "<icon> 0.76", same thresholds as the full report; "n/a" when empty.
fmt() {
  if [[ -z "$1" ]]; then echo "n/a"; return; fi
  awk -v s="$1" 'BEGIN {
    icon = s >= 0.8 ? ":green_circle:" : s >= 0.5 ? ":yellow_circle:" : ":red_circle:"
    printf "%s %.2f", icon, s
  }'
}

delta=""
if [[ -n "${OVERALL:-}" && -n "${BASE_OVERALL:-}" ]]; then
  delta=$(awk -v h="$OVERALL" -v b="$BASE_OVERALL" 'BEGIN {
    d = h - b
    printf "%s %+.2f", (d > 0.005 ? ":arrow_up:" : d < -0.005 ? ":arrow_down:" : ":heavy_minus_sign:"), d
  }')
fi

body="$(
  key="${KEY//[^A-Za-z0-9._\/-]/_}"  # ends up in a jq string literal below
  echo "<!-- pats-comment:$key -->"
  echo "**pats overall score**"
  echo
  echo "| | score |"
  echo "|---|---:|"
  echo "| this pr | **$(fmt "${OVERALL:-}")** |"
  echo "| base \`${BASE_REF:-?}\` | $(fmt "${BASE_OVERALL:-}") |"
  if [[ -n "$delta" ]]; then echo "| change | $delta |"; fi
  echo
  echo "see the [run summary]($run_url) for further details."
)"
marker="$(head -n1 <<< "$body")"
payload="$(jq -Rs '{body: .}' <<< "$body")"

id="$(gh api --paginate "repos/$repo/issues/$PR/comments" \
  --jq ".[] | select(.body | startswith(\"$marker\")) | .id" | tail -n1)"
if [[ -n "$id" ]]; then
  gh api -X PATCH "repos/$repo/issues/comments/$id" --input - --jq .html_url <<< "$payload"
else
  gh api -X POST "repos/$repo/issues/$PR/comments" --input - --jq .html_url <<< "$payload"
fi
