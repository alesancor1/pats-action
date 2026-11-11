#!/usr/bin/env bash
# assembles the json report (README.md#report-json) from the latest pats run in
# the cwd, writes it to $RUNNER_TEMP/pats-report/pats-report.json, and exports
# report / run-dir / overall to $GITHUB_OUTPUT.
#
# env: RUN_RC, SCORE_RC (may be empty if pats.sh never ran).
set -euo pipefail

out="$RUNNER_TEMP/pats-report/pats-report.json"
mkdir -p "$(dirname "$out")"

run_dir="$(find .pats/runs -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -n1 || true)"
if [[ -n "$run_dir" ]]; then
  run_dir="$(cd "$run_dir" && pwd)"
fi

# owner/name from the checkout's origin, else the workflow's repo.
repo="$(git remote get-url origin 2>/dev/null | sed -E 's#^.*github\.com[:/]##; s#\.git$##' || true)"
sha="$(git rev-parse HEAD 2>/dev/null || echo "$GITHUB_SHA")"

scores=null
pairs='[]'
if [[ -n "$run_dir" ]]; then
  if [[ -f "$run_dir/scores.json" ]]; then
    scores="$(cat "$run_dir/scores.json")"
  fi
  mapfile -t metas < <(find "$run_dir" -mindepth 3 -maxdepth 3 -name metadata.json | sort)
  if (( ${#metas[@]} )); then
    pairs="$(jq -s . "${metas[@]}")"
  fi
fi

jq -n \
  --arg repository "${repo:-$GITHUB_REPOSITORY}" \
  --arg sha "$sha" \
  --arg pats_version "$(pats --version 2>/dev/null | head -n1)" \
  --arg run_name "$(basename "${run_dir:-}")" \
  --arg run_rc "${RUN_RC:-}" \
  --arg score_rc "${SCORE_RC:-}" \
  --arg workflow_run_url "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID" \
  --argjson scores "$scores" \
  --argjson pairs "$pairs" \
  '{
    schema_version: 1,
    repository: $repository,
    sha: $sha,
    pats_version: $pats_version,
    run_name: (if $run_name == "" then null else $run_name end),
    run_exit_code: ($run_rc | tonumber? // null),
    score_exit_code: ($score_rc | tonumber? // null),
    workflow_run_url: $workflow_run_url,
    scores: $scores,
    pairs: $pairs
  }' > "$out"

{
  echo "report=$out"
  echo "run-dir=$run_dir"
  echo "overall=$(jq -r '.scores.overall // empty' "$out")"
} >> "$GITHUB_OUTPUT"
