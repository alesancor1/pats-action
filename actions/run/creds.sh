#!/usr/bin/env bash
# usage: creds.sh write|remove
#
# pats' keyless harnesses read their login from files in $HOME. `write` creates
# them from CLAUDE_CREDENTIALS / CODEX_AUTH (when set); `remove` deletes them.
# token-style creds (CLAUDE_CODE_OAUTH_TOKEN, ...) need nothing -- pats reads
# them from the env directly.
set -euo pipefail

claude="$HOME/.claude/.credentials.json"
codex="$HOME/.codex/auth.json"

case "${1:-}" in
  write)
    umask 077
    if [[ -n "${CLAUDE_CREDENTIALS:-}" ]]; then
      mkdir -p "$(dirname "$claude")"
      printf '%s' "$CLAUDE_CREDENTIALS" > "$claude"
    fi
    if [[ -n "${CODEX_AUTH:-}" ]]; then
      mkdir -p "$(dirname "$codex")"
      printf '%s' "$CODEX_AUTH" > "$codex"
    fi
    ;;
  remove)
    rm -f "$claude" "$codex"
    ;;
  *)
    echo "usage: $0 write|remove" >&2
    exit 2
    ;;
esac
