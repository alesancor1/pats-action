#!/usr/bin/env bash
# runs shellcheck over every script in the repo.
set -euo pipefail

cd "$(dirname "$0")/../.."
mapfile -t scripts < <(find actions .github/scripts -name '*.sh' | sort)
shellcheck -S warning "${scripts[@]}"
echo "shellcheck: ${#scripts[@]} scripts ok"
