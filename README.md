# pats-action

github actions + a reusable workflow for [pats](https://github.com/lczyk/pats).
pats is untouched; this repo only installs and drives it.

| piece | inputs | what it does |
|---|---|---|
| [`actions/run`](actions/run/action.yaml) | `pats-channel`, `working-directory`, `init-args`, `run-args`, `score-args`, `artifact-name`, `skip-missing-suites` | installs the pats snap, runs `pats init` + `pats run` + `pats score`, uploads a **json report** artifact |
| [`actions/report`](actions/report/action.yaml) | `artifact-name` | renders the json as markdown, writes the job summary |
| [`actions/comment`](actions/comment/action.yaml) | `overall`, `base-overall`, `key`, `name`, `github-token` | sticky pr comment with the overall score vs the base branch's + a link to the run summary, updated on re-runs |
| [`Pats.yaml`](.github/workflows/Pats.yaml) | `repository`, `ref`, `working-directory`, `pats-channel`, `name`, `init-args`, `run-args`, `score-args`, `max-regression`, `fail-under`, `environment` | checkout -> run (head + base on prs) -> report -> comment -> regression check |

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
      pats-channel: latest/stable
      run-args: -S smoke -j -1
      score-args: -S smoke
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

## one job per suite

called once, the workflow scores everything `run-args` selects as one number:
one base run, one comment, one regression check. to give each suite its own,
call it from a matrix and `name` each call:

```yaml
jobs:
  pats:
    strategy:
      fail-fast: false
      matrix:
        suite: [smoke, slow]
    uses: alesancor1/pats-action/.github/workflows/Pats.yaml@<sha> # vX.Y.Z
    permissions:
      contents: read
      pull-requests: write
    with:
      name: ${{ matrix.suite }}
      init-args: -S ${{ matrix.suite }}
      run-args: -S ${{ matrix.suite }} -j -1
      score-args: -S ${{ matrix.suite }}
      max-regression: "0.05"
    secrets:
      OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

- `name` is what keeps the calls apart: its report artifacts are
  `pats-report-head-<name>` / `pats-report-base-<name>`, and its pr comment is
  its own, headed with the name. two calls in one run without it fail on the
  artifact name. letters, digits, `.`, `_` and `-` only: any other name fails
  the call before pats runs.
- `init-args` keeps a job to the sandboxes its suite uses. without it every
  job makes every sandbox in the config.
- a suite the base branch doesn't have yet skips its base run (no base
  score, so no regression check), and each suite is held to `max-regression` against its own base score.
- under an `environment`, each call's run jobs wait for approval on their own.

## lxd image cache

a runner is a new lxd server every job, so `pats init` builds an lxd sandbox's
images every time (minutes for a big one). `image-cache: true` keeps them in
the actions cache instead:

- before init, the newest cache for this pats version and `init-args` is
  restored, and init takes from it every image whose key still matches
  (`pats init --image-cache`). a stale image is rebuilt, never used.
- after a successful init, the server's `pats-img-*` images are exported into
  it, the ones it no longer has dropped, and the cache saved under a new key,
  only when the set differs from the restored cache's. an export that fails
  leaves a warning, not a failed run.
- nothing is saved from `pull_request_target`: its code isn't reviewed, and a
  cache it saved would be the base branch's.
- only jobs with an lxd sandbox, and only container ones (pats' vm images
  don't go through the directory). calls with the same `init-args` share a
  cache; a big image counts against the repo's cache quota once per
  `init-args`.

## credentials

the workflow takes these secrets, all optional. pass only the ones your agents use:

| secret | agent kind |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude-cli-keyless`, from `claude setup-token` (preferred) |
| `ANTHROPIC_API_KEY` | `claude-cli-keyless` |
| `COPILOT_GITHUB_TOKEN` | `copilot-cli-keyless` |
| `OPENROUTER_API_KEY` | `opencode-openrouter` |
| `PATS_CHECKOUT_TOKEN` | read access to a private `repository` |

with `actions/run` directly, pass them as step `env` under the same names.
login files (`~/.claude/.credentials.json`, `~/.codex/auth.json`) aren't
supported: use the token forms. `codex-cli-keyless` has no token form, so it
can't run in ci.

## fork prs

a pr from a fork gets no secrets on `pull_request`, so its agents can't
authenticate. to evaluate one, run on `pull_request_target` behind an
environment:

```yaml
# .github/workflows/pats-forks.yaml
name: pats (forks)
on: pull_request_target

jobs:
  pats:
    if: github.event.pull_request.head.repo.full_name != github.repository
    uses: alesancor1/pats-action/.github/workflows/Pats.yaml@<sha> # vX.Y.Z
    permissions:
      contents: read
      pull-requests: write
    with:
      environment: pats-forks
      run-args: -S smoke -j -1
      score-args: -S smoke
    secrets:
      OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

- the environment needs **required reviewers**. the run job waits for one of
  them, and each push to the pr is a new run to approve. an environment with no
  reviewers gates nothing.
- the fork's head is checked out only on `pull_request_target` with an
  `environment` set, and by sha, so an approval covers that one commit.
- keep the keys as secrets of that environment, under the names in
  [credentials](#credentials), and still pass them in `secrets:`: a reusable
  workflow sees only what its caller passes. in the run job the environment's
  secret wins over a repo secret of the same name.
- approving a run trusts the commit: the fork's `pats.yaml`, steps and skills
  all run with the key. use a key with a spend cap, apart from the one your own
  prs use.
- give the `pull_request` workflow the opposite `if`, so a fork pr skips it.

## using the actions directly

```yaml
steps:
  - uses: actions/checkout@<sha>
  - uses: alesancor1/pats-action/actions/run@<sha>
    with:
      pats-channel: latest/stable
      run-args: -S smoke
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
  "schema_version": 2,
  "repository": "owner/name", "sha": "<full sha>", "pats_version": "1.0.0",
  "run_exit_code": 0, "score_exit_code": 0,  // null if the step didn't run
  "workflow_run_url": "https://github.com/...",
  "report": { /* `pats report --json` verbatim: run, overall, agents, pairs, scores */ }  // or null
}
```

`report` is pats' own machine interface to a run's results (version 1, see
pats' `docs/spec/report.md`); pats treats its run-dir files (`scores.json`,
`metadata.json`) as internal. it's `null` when the run was never scored.

## notes

- **fork prs** get no secrets on `pull_request`. see [fork prs](#fork-prs), and
  don't run `pull_request_target` on a fork's head without an environment that
  has required reviewers: the fork's config and scripts get your keys.
- all third-party actions are pinned to a commit sha (version in a trailing comment).
- `job.workflow_*` isn't available on GitHub Enterprise Server.
- needs a runner with docker and snapd. any `ubuntu-*` hosted runner works.
- pats is installed as a **strict snap** (`sudo snap install pats --channel=...`
  plus `sudo snap connect pats:docker`), which means:
  - `pats.yaml` must be in the pats 1.x format.
  - every task/scorer script (`stage`, `collect`, `prompt-cmd`, `score`) needs a
    `step-sandbox`: the snap runs nothing on the host.
  - the project must sit under the home and not in a hidden dir; any checkout
    under `GITHUB_WORKSPACE` is fine.
- `pats init` runs with no selectors unless `init-args` gives some, so it
  makes every sandbox the config uses, not just the ones `run-args` selects.
- engines: docker is always connected (`pats:docker`). if any sandbox in
  `pats list sandboxes` (agent or step sandbox) uses `driver: lxd`, the run
  action also installs and initialises the lxd snap, lets pats' bridges past
  docker's firewall, and connects `pats:lxd`. podman, bwrap and the host driver
  aren't in the snap.

## development

```sh
python -m pytest -q tests   # renderer and script tests
bash .github/scripts/shellcheck.sh  # all scripts
```
