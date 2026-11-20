#!/usr/bin/env bash
# runs `pats init` (makes and pins the sandbox images; `pats run` no longer
# builds or pulls), then `pats run` and `pats score`. score runs even if run
# failed -- a partial run still scores. never fails itself: the exit codes go
# to $GITHUB_OUTPUT as run-exit-code / score-exit-code so the report is
# collected either way. a failed init counts as a failed run.
#
# with SKIP_MISSING_SUITES=true, a suite selected with -S / --suite that the
# config doesn't define (e.g. the base branch of a pr adding it) skips the
# whole run: nothing is run, and skipped=true goes to $GITHUB_OUTPUT.
#
# with IMAGE_CACHE_DIR set, init takes the lxd images it would build from that
# directory where it can (`pats init --image-cache`).
#
# INIT_ARGS / RUN_ARGS / SCORE_ARGS are split on whitespace (no quoting).
set -uo pipefail

read -ra init_args <<< "${INIT_ARGS:-}"
if [[ -n "${IMAGE_CACHE_DIR:-}" ]]; then
  init_args+=(--image-cache "$IMAGE_CACHE_DIR")
fi
read -ra run_args <<< "${RUN_ARGS:-}"
read -ra score_args <<< "${SCORE_ARGS:-}"

# prints the suite names selected in the given args, one per line.
selected_suites() {
  local arg next=0
  for arg in "$@"; do
    if [[ "$next" == 1 ]]; then
      echo "$arg"
      next=0
      continue
    fi
    case "$arg" in
      -S | --suite) next=1 ;;
      --suite=*) echo "${arg#--suite=}" ;;
      -S*) echo "${arg#-S}" ;;
    esac
  done | tr ',' '\n' | sed '/^$/d' | sort -u
}

if [[ "${SKIP_MISSING_SUITES:-false}" == "true" ]]; then
  wanted="$(selected_suites "${init_args[@]}" "${run_args[@]}" "${score_args[@]}")"
  if [[ -n "$wanted" ]]; then
    if known="$(pats list suites 2>&1)"; then
      known="$(awk 'NR > 1 { print $2 }' <<< "$known" | sort -u)"
      missing="$(comm -23 <(echo "$wanted") <(echo "$known") | paste -sd ' ')"
      if [[ -n "$missing" ]]; then
        echo "::warning::suite(s) not in this config, skipping the run: $missing"
        echo "skipped=true" >> "$GITHUB_OUTPUT"
        exit 0
      fi
    else
      echo "pats list suites failed, not checking for missing suites: $known" >&2
    fi
  fi
fi

pats init "${init_args[@]}"
run_rc=$?
init_rc=$run_rc
if [[ "$run_rc" == 0 ]]; then
  pats run "${run_args[@]}"
  run_rc=$?
fi
pats score "${score_args[@]}"
score_rc=$?

{
  echo "skipped=false"
  echo "init-exit-code=$init_rc"
  echo "run-exit-code=$run_rc"
  echo "score-exit-code=$score_rc"
} >> "$GITHUB_OUTPUT"
