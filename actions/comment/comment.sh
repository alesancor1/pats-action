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
base="${BASE_REF:-base}"

# "<icon> 0.76", same thresholds as the full report; "n/a" when empty.
# literal emoji, not :shortcodes: -- those don't render inside html blocks.
fmt() {
  if [[ -z "$1" ]]; then echo "n/a"; return; fi
  awk -v s="$1" 'BEGIN {
    icon = s >= 0.8 ? "🟢" : s >= 0.5 ? "🟡" : "🔴"
    printf "%s %.2f", icon, s
  }'
}

# change cell + a one-line verdict; both empty without a base score.
delta="" verdict=""
if [[ -n "${OVERALL:-}" && -n "${BASE_OVERALL:-}" ]]; then
  d="$(awk -v h="$OVERALL" -v b="$BASE_OVERALL" 'BEGIN { printf "%+.2f", h - b }')"
  case "$d" in
    +0.00|-0.00) delta="➖ $d" verdict="➖ **No change** vs \`$base\`" ;;
    +*)          delta="📈 $d" verdict="📈 **Improved** vs \`$base\`" ;;
    *)           delta="📉 $d" verdict="📉 **Regressed** vs \`$base\`" ;;
  esac
fi

cell() { printf '<td align="center"><h2>%s</h2></td>' "$1"; }

body="$(
  key="${KEY//[^A-Za-z0-9._\/-]/_}"  # ends up in a jq string literal below
  echo "<!-- pats-comment:$key -->"
  echo "## 🧪 pats evaluation"
  echo
  if [[ -n "$verdict" ]]; then echo "$verdict"; echo; fi
  echo '<table>'
  printf '<tr><th>This PR</th><th>Base <code>%s</code></th>' "$base"
  if [[ -n "$delta" ]]; then printf '<th>Change</th>'; fi
  echo '</tr>'
  printf '<tr>%s%s' "$(cell "$(fmt "${OVERALL:-}")")" "$(cell "$(fmt "${BASE_OVERALL:-}")")"
  if [[ -n "$delta" ]]; then cell "$delta"; fi
  echo '</tr>'
  echo '</table>'
  echo
  echo "📊 **[View the full report]($run_url)**: per-task scores, scorer breakdown and run stats."
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
