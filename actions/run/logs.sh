#!/usr/bin/env bash
# stages the run's logs in $RUNNER_TEMP/pats-logs for upload: the run dir as
# run/ and the `pats init` logs as init/. regular files only. the value of each
# harness credential in the env is replaced by its name in the copies -- as
# written, an encoded one is not found. exports `dir` to $GITHUB_OUTPUT when
# anything was staged.
#
# env: RUN_DIR (may be empty). runs from the dir holding pats.yaml.
set -euo pipefail

out="$RUNNER_TEMP/pats-logs"
rm -rf "$out"
mkdir -p "$out"

# -P: a link is copied as a link, not followed, and dropped below.
if [[ -d "${RUN_DIR:-}" ]]; then
  cp -RP "$RUN_DIR" "$out/run" || echo "::warning::logs: not all of the run dir could be copied"
fi
if [[ -d .pats/init ]]; then
  cp -RP .pats/init "$out/init" || echo "::warning::logs: not all of the init logs could be copied"
fi
find "$out" ! -type f ! -type d -delete
chmod -R u+rwX "$out"

# a failure here ends the script before `dir` is exported: nothing is uploaded.
# shellcheck disable=SC2016
find "$out" -type f -exec perl -pi -e '
  BEGIN {
    for my $name (qw(CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY OPENROUTER_API_KEY COPILOT_GITHUB_TOKEN)) {
      (my $value = $ENV{$name} // "") =~ s/^\s+|\s+$//g;
      $values{$name} = $value if length $value;
    }
  }
  for my $name (keys %values) { s/\Q$values{$name}\E/[$name]/g }' {} +

if [[ -n "$(find "$out" -type f -print -quit)" ]]; then
  echo "dir=$out" >> "$GITHUB_OUTPUT"
fi
