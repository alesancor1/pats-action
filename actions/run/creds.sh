#!/usr/bin/env bash
# usage: creds.sh write|remove
#
# the keyless harnesses read a login file. the pats snap can't read hidden
# dirs in the home (~/.claude, ~/.codex), so `write` puts CLAUDE_CREDENTIALS /
# CODEX_AUTH (when set) in a plain dir under the home and points pats at them
# via PATS_CLAUDE_AUTH_PATH / PATS_CODEX_AUTH_PATH. `remove` deletes them.
# token-style creds (CLAUDE_CODE_OAUTH_TOKEN, ...) need nothing -- pats reads
# them from the env directly.
set -euo pipefail

dir="$HOME/pats-auth"

case "${1:-}" in
  write)
    umask 077
    mkdir -p "$dir"
    if [[ -n "${CLAUDE_CREDENTIALS:-}" ]]; then
      printf '%s' "$CLAUDE_CREDENTIALS" > "$dir/claude.json"
      echo "PATS_CLAUDE_AUTH_PATH=$dir/claude.json" >> "$GITHUB_ENV"
    fi
    if [[ -n "${CODEX_AUTH:-}" ]]; then
      printf '%s' "$CODEX_AUTH" > "$dir/codex.json"
      echo "PATS_CODEX_AUTH_PATH=$dir/codex.json" >> "$GITHUB_ENV"
    fi
    ;;
  remove)
    rm -rf "$dir"
    ;;
  *)
    echo "usage: $0 write|remove" >&2
    exit 2
    ;;
esac
