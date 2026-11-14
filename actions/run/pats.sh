#!/usr/bin/env bash
# runs `pats init` (makes and pins the sandbox images; `pats run` no longer
# builds or pulls), then `pats run` and `pats score`. score runs even if run
# failed -- a partial run still scores. never fails itself: the exit codes go
# to $GITHUB_OUTPUT as run-exit-code / score-exit-code so the report is
# collected either way. a failed init counts as a failed run.
#
# RUN_ARGS / SCORE_ARGS are split on whitespace (no quoting).
set -uo pipefail

read -ra run_args <<< "${RUN_ARGS:-}"
read -ra score_args <<< "${SCORE_ARGS:-}"

pats init
run_rc=$?
if [[ "$run_rc" == 0 ]]; then
  pats run "${run_args[@]}"
  run_rc=$?
fi
pats score "${score_args[@]}"
score_rc=$?

{
  echo "run-exit-code=$run_rc"
  echo "score-exit-code=$score_rc"
} >> "$GITHUB_OUTPUT"
