#!/usr/bin/env bash
# installs pats@$PATS_VERSION into $RUNNER_TEMP/pats-bin and puts it on PATH.
set -euo pipefail

: "${PATS_VERSION:?}"

bin="$RUNNER_TEMP/pats-bin"
# GOTOOLCHAIN=auto lets the stable go from setup-go fetch whatever pats' go.mod needs.
GOBIN="$bin" GOTOOLCHAIN=auto go install "github.com/lczyk/pats/cmd/pats@$PATS_VERSION"
echo "$bin" >> "$GITHUB_PATH"
"$bin/pats" --version
