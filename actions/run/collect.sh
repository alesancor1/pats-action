#!/usr/bin/env bash
# assembles the json report (README.md#report-json) for the latest pats run in
# the cwd: pats' own `pats report --json` document plus where it came from.
# writes it to $RUNNER_TEMP/pats-report/pats-report.json and exports report /
# run-dir / overall to $GITHUB_OUTPUT.
#
# env: RUN_RC, SCORE_RC (may be empty if pats.sh never ran).
set -euo pipefail

out="$RUNNER_TEMP/pats-report/pats-report.json"
mkdir -p "$(dirname "$out")"

# the document is pats' interface to a run's results (its run-dir files are
# internal). it fails when the run was never scored: report null then.
report="$(pats report --json 2>/dev/null)" || report=null
[[ -n "$report" ]] || report=null

# the run dir, for uploading logs: from the document, else the newest run.
run_dir="$(jq -r '.run.dir // empty' <<< "$report")"
if [[ -z "$run_dir" ]]; then
  run_dir="$(find .pats/runs -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -n1 || true)"
  if [[ -n "$run_dir" ]]; then
    run_dir="$(cd "$run_dir" && pwd)"
  fi
fi

# owner/name from the checkout's origin, else the workflow's repo.
repo="$(git remote get-url origin 2>/dev/null | sed -E 's#^.*github\.com[:/]##; s#\.git$##' || true)"
sha="$(git rev-parse HEAD 2>/dev/null || echo "$GITHUB_SHA")"

jq -n \
  --arg repository "${repo:-$GITHUB_REPOSITORY}" \
  --arg sha "$sha" \
  --arg pats_version "$(pats --version 2>/dev/null | head -n1)" \
  --arg run_rc "${RUN_RC:-}" \
  --arg score_rc "${SCORE_RC:-}" \
  --arg workflow_run_url "$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID" \
  --argjson report "$report" \
  '{
    schema_version: 2,
    repository: $repository,
    sha: $sha,
    pats_version: $pats_version,
    run_exit_code: ($run_rc | tonumber? // null),
    score_exit_code: ($score_rc | tonumber? // null),
    workflow_run_url: $workflow_run_url,
    report: $report
  }' > "$out"

{
  echo "report=$out"
  echo "run-dir=$run_dir"
  echo "overall=$(jq -r '.report.overall // empty' "$out")"
} >> "$GITHUB_OUTPUT"
