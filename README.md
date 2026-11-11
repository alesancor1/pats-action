# pats-action

github actions + a reusable workflow for [pats](https://github.com/lczyk/pats).
pats is untouched; this repo only installs and drives it.

| piece | inputs | what it does |
|---|---|---|
| [`actions/run`](actions/run/action.yaml) | `pats-version`, `working-directory`, `run-args`, `score-args`, `artifact-name` | installs pats, runs `pats run` + `pats score`, uploads a **json report** artifact |
| [`actions/report`](actions/report/action.yaml) | `artifact-name` | renders the json as markdown, writes the job summary |
| [`actions/comment`](actions/comment/action.yaml) | `overall`, `base-overall`, `key`, `github-token` | sticky pr comment with the overall score vs the base branch's + a link to the run summary, updated on re-runs |
| [`Pats.yaml`](.github/workflows/Pats.yaml) | `repository`, `ref`, `working-directory`, `pats-version`, `run-args`, `score-args`, `max-regression`, `fail-under` | checkout -> run (head + base on prs) -> report -> comment -> regression check |

the logic lives in scripts next to each action (`actions/*/*.sh`,
`render_report.py`, and `.github/scripts/` for the workflows), and the yaml only wires inputs to them.

## quick start

```yaml
# .github/workflows/pats.yaml in the repo holding pats.yaml
name: pats
on: [pull_request, workflow_dispatch]

jobs:
  pats:
    uses: alesancor1/pats-action/.github/workflows/Pats.yaml@<sha> # vX.Y.Z
    permissions:
      contents: read
      pull-requests: write
    with:
      pats-version: v0.7.6
      run-args: -s smoke -j -1
      score-args: -s smoke
      max-regression: "0.05"
      fail-under: "0.8"
    secrets:
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
      OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

to test another repo, set `repository` (+ `ref`), and pass `PATS_CHECKOUT_TOKEN`
if that repo is private. the full report goes to the run summary; the pr comment
(on the caller's pr) only holds the overall score and a link to it. on non-pr events
(e.g. `workflow_dispatch`) there's no comment, only the job summary. if pats
fails, the workflow stops after `run`. there's no comment then either, but the
json report is still uploaded as the `pats-report-head` artifact.

on prs, the workflow also runs pats on the head of the base branch (in parallel)
so the comment can show both scores and the change. this doubles the agent cost
of a pr run. a failing base run doesn't block the report; its score shows as n/a.
the base comparison is skipped when `repository` is set.

with `max-regression` set, a pr fails when its score is more than that below the
base branch's (e.g. `0.05`: base 0.80 -> pr 0.74 fails, 0.76 passes). if there's no
base score, the check is skipped with a warning.

with `fail-under` set, the run fails whenever the overall score is below it
(e.g. `0.8`), on any event. a missing score also fails.

the workflow checks itself out at the pinned commit (via `job.workflow_repository`
/ `job.workflow_sha`) and uses its actions by path (`./.pats-action/actions/...`).
the actions therefore always match the workflow version you pinned, with no
separate tag to keep in sync.

## credentials

the workflow takes these secrets, all optional. pass only the ones your agents use:

| secret | agent kind |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude-cli-keyless`, from `claude setup-token` (preferred) |
| `ANTHROPIC_API_KEY` | `claude-cli-keyless` |
| `CLAUDE_CREDENTIALS` | `claude-cli-keyless`, contents of `~/.claude/.credentials.json` |
| `CODEX_AUTH` | `codex-cli-keyless`, contents of `~/.codex/auth.json` |
| `COPILOT_GITHUB_TOKEN` | `copilot-cli-keyless` |
| `OPENROUTER_API_KEY` | `opencode-openrouter` |
| `PATS_CHECKOUT_TOKEN` | read access to a private `repository` |

with `actions/run` directly, pass them as step `env` under the same names.
`CLAUDE_CREDENTIALS` / `CODEX_AUTH` are written to their files with mode 600 and
deleted afterwards. they hold rotating refresh tokens, so prefer the token forms.

## using the actions directly

```yaml
steps:
  - uses: actions/checkout@<sha>
  - uses: alesancor1/pats-action/actions/run@<sha>
    with:
      pats-version: v0.7.6
      run-args: -s smoke
    env:
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
  - id: report
    if: always()
    uses: alesancor1/pats-action/actions/report@<sha>
  - if: always()
    uses: alesancor1/pats-action/actions/comment@<sha>
    with:
      overall: ${{ steps.report.outputs.overall }}
```

`run-args` / `score-args` are split on whitespace (no quoting). the run action
fails when pats does, but only after it uploads the report. it outputs `run-dir`
if you want to upload the full logs yourself.

## report json

the contract between `run` and `report`. anything else can consume it too.

```jsonc
{
  "schema_version": 1,
  "repository": "owner/name", "sha": "<full sha>", "pats_version": "0.7.6",
  "run_name": "001-20261111-foo-bar",        // null if pats made no run
  "run_exit_code": 0, "score_exit_code": 0,
  "workflow_run_url": "https://github.com/...",
  "scores": { /* pats' scores.json verbatim */ },          // or null
  "pairs":  [ /* each pair's metadata.json verbatim */ ]
}
```

## notes

- **fork prs** get no secrets, so the agents can't authenticate. don't use
  `pull_request_target` plus a checkout of the fork's head. that runs untrusted
  scripts on the host with your secrets.
- all third-party actions are pinned to a commit sha (version in a trailing comment).
- `job.workflow_*` isn't available on GitHub Enterprise Server.
- needs a runner with docker. any `ubuntu-*` hosted runner works. the run job
  also installs `uv`, since pats runs task/scorer scripts on the host and
  `#!/usr/bin/env -S uv run --script` shebangs are the usual pattern.

## development

```sh
python -m pytest -q tests   # renderer tests
bash .github/scripts/shellcheck.sh  # all scripts
```
