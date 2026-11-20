#!/usr/bin/env bash
# fails when $NAME, the name a caller gave this call, has a character outside
# letters, digits, `.`, `_` and `-`. the name ends up in the report artifacts'
# names, which upload-artifact restricts, and in the pr comment's key and
# heading: a bad one is refused here, before pats spends anything.
#
# env: NAME (may be empty: an unnamed call).
set -euo pipefail

LC_ALL=C  # ranges mean ascii, whatever the runner's locale
if [[ "${NAME:-}" =~ [^A-Za-z0-9._-] ]]; then
  shown="${NAME//[^A-Za-z0-9._-]/?}"  # not the raw value: it would reach the log as is
  echo "::error::name '$shown' is not valid: letters, digits, '.', '_' and '-' only ('?' marks the rest)"
  exit 1
fi
