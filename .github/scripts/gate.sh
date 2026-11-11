#!/usr/bin/env bash
# fails when the pr head's overall score is more than $MAX_REGRESSION below
# the base branch's.
#
# env: MAX_REGRESSION (empty -> no-op), OVERALL, BASE_OVERALL (may be empty).
set -euo pipefail

if [[ -z "${MAX_REGRESSION:-}" ]]; then
  exit 0
fi
if [[ -z "${OVERALL:-}" ]]; then
  echo "::error::the pr head has no overall score"
  exit 1
fi
if [[ -z "${BASE_OVERALL:-}" ]]; then
  echo "::warning::no base score to compare against, skipping the regression check"
  exit 0
fi
if awk -v h="$OVERALL" -v b="$BASE_OVERALL" -v m="$MAX_REGRESSION" 'BEGIN { exit !(b - h > m) }'; then
  echo "::error::score dropped from $BASE_OVERALL (base) to $OVERALL (pr), more than max-regression=$MAX_REGRESSION"
  exit 1
fi
echo "score $OVERALL vs base $BASE_OVERALL: within max-regression=$MAX_REGRESSION"
