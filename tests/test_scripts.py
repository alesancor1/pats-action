import os
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMMENT = ROOT / "actions" / "comment" / "comment.sh"
NAME = ROOT / ".github" / "scripts" / "name.sh"

ENV = {
    "KEY": "acme/skills/tests",
    "GITHUB_REPOSITORY": "acme/skills",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_RUN_ID": "1",
    "BASE_REF": "main",
    "OVERALL": "0.80",
    "BASE_OVERALL": "0.70",
}


def run(script, *args, **env):
    return subprocess.run(
        ["bash", str(script), *args],
        env={"PATH": os.environ["PATH"], **env},
        capture_output=True,
        text=True,
        check=False,
    )


def body(**env):
    proc = run(COMMENT, "--dry-run", **{**ENV, **env})
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.splitlines()


# --- comment.sh ---------------------------------------------------------------


def test_comment_layout():
    lines = body()
    assert lines[0] == "<!-- pats-comment:acme/skills/tests -->"
    assert lines[1] == "### pats evaluation"
    assert lines[3].startswith("`main` ")
    assert lines[5].startswith("[full report](https://github.com/acme/skills/actions/runs/1)")
    assert [i for i, line in enumerate(lines) if not line] == [2, 4] and len(lines) == 6
    assert "\n".join(lines).isascii()


def test_comment_shows_the_base_score_first():
    assert body()[3] == (
        "`main` :yellow_circle: 0.70 &rarr; PR :green_circle: **0.80**"
        " &middot; :chart_with_upwards_trend: **+0.10**"
    )


@pytest.mark.parametrize(
    ("overall", "base", "shown"),
    [
        ("0.60", "0.70", "PR :yellow_circle: **0.60** &middot; :chart_with_downwards_trend: **-0.10**"),
        ("0.699", "0.70", "PR :yellow_circle: **0.70** &middot; no change"),
        ("0.80", "", "`main` n/a &rarr; PR :green_circle: **0.80**"),
        ("", "0.70", "`main` :yellow_circle: 0.70 &rarr; PR n/a"),
        ("0.79", "0.49", "`main` :red_circle: 0.49 &rarr; PR :yellow_circle: **0.79** "),
        ("0.5", "1", "`main` :green_circle: 1.00 &rarr; PR :yellow_circle: **0.50** "),
    ],
)
def test_comment_scores(overall, base, shown):
    line = body(OVERALL=overall, BASE_OVERALL=base)[3]
    assert shown in line
    assert ("trend" in line or "no change" in line) == bool(overall and base)


def test_comment_named_heading():
    assert body(NAME="ci-rock-crafter")[1] == "### pats evaluation: `ci-rock-crafter`"


@pytest.mark.parametrize(
    "name",
    ["a`b", "<script>alert(1)</script>", "a\nb", "a & b", "## heading", "a|b", "a** b"],
)
def test_comment_hostile_name_stays_one_code_span(name):
    # the marker is what finds the sticky comment: the name must not move it,
    # nor change any line but the heading
    plain, named = body(), body(NAME=name)
    assert [i for i, (a, b) in enumerate(zip(plain, named)) if a != b] == [1]
    assert len(named) == len(plain)
    shown = named[1].split("### pats evaluation: ", 1)[1]
    assert shown.startswith("`") and shown.endswith("`")
    assert set(shown[1:-1]) <= set("abcdefghijklmnopqrstuvwxyz1()_.-")


def test_comment_hostile_base_ref_stays_one_code_span():
    line = body(BASE_REF="rel/1.x`[l](https://example.com)`")[3]
    assert line.startswith("`rel/1.x__l__https_//example.com__` :yellow_circle: 0.70 &rarr; ")


def test_comment_key_names_the_marker():
    assert body(KEY="acme/skills/tests/smoke")[0] == "<!-- pats-comment:acme/skills/tests/smoke -->"


def test_comment_dry_run_needs_no_token():
    assert "GH_TOKEN" not in ENV and "PR" not in ENV
    assert run(COMMENT, "-n", **ENV).returncode == 0


def test_comment_posting_needs_a_token():
    proc = run(COMMENT, **ENV)
    assert proc.returncode != 0
    assert "GH_TOKEN" in proc.stderr


def test_comment_unknown_argument():
    proc = run(COMMENT, "--nope", **ENV)
    assert proc.returncode == 2
    assert proc.stderr.startswith("usage: comment.sh")


@pytest.mark.parametrize(("overall", "shown"), [("", "PR n/a"), ("0.41", "PR :red_circle: **0.41**")])
def test_comment_failed_run_says_so_in_place_of_the_change(overall, shown):
    line = body(RUN_FAILED="true", OVERALL=overall)[3]
    assert line == f"`main` :yellow_circle: 0.70 &rarr; {shown} &middot; :x: **run failed**"


def test_comment_run_that_did_not_fail_shows_the_change():
    assert body(RUN_FAILED="false") == body()


# a stand-in for `gh`: logs each call, answers the pr head and the id of the
# comment found, swallows a write.
GH = """#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
case "$*" in
  *"/pulls/"*) [[ "$GH_HEAD" != fail ]] || exit 1; echo "$GH_HEAD" ;;
  *--paginate*) printf '%s' "$GH_FOUND" ;;
  *) cat > /dev/null; echo "https://github.com/acme/skills/pull/7#issuecomment-1" ;;
esac
"""


def post(tmp_path, found="", head="aaaaaaa1", **env):
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text(GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.touch()
    proc = run(
        COMMENT,
        **{
            **ENV,
            "PATH": f"{gh.parent}{os.pathsep}{os.environ['PATH']}",
            "GH_TOKEN": "t",
            "PR": "7",
            "GH_LOG": str(log),
            "GH_FOUND": found,
            "GH_HEAD": head,
            **env,
        },
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout, [call for call in log.read_text().splitlines() if "-X " in call]


def test_comment_posts_when_there_is_none(tmp_path):
    _, writes = post(tmp_path, HEAD_SHA="aaaaaaa1")
    assert len(writes) == 1 and "-X POST repos/acme/skills/issues/7/comments " in writes[0]


def test_comment_updates_the_one_found(tmp_path):
    _, writes = post(tmp_path, found="42", HEAD_SHA="aaaaaaa1")
    assert len(writes) == 1 and "-X PATCH repos/acme/skills/issues/comments/42 " in writes[0]


@pytest.mark.parametrize("found", ["", "42"])
def test_comment_of_a_commit_the_pr_moved_on_from_writes_nothing(tmp_path, found):
    out, writes = post(tmp_path, found=found, head="bbbbbbb2", HEAD_SHA="aaaaaaa1")
    assert writes == []
    assert "::notice::the pr head moved from aaaaaaa to bbbbbbb" in out


def test_comment_without_a_head_sha_is_not_held_back(tmp_path):
    _, writes = post(tmp_path, head="bbbbbbb2")
    assert len(writes) == 1


@pytest.mark.parametrize("head", ["fail", ""])
def test_comment_is_written_when_the_pr_head_cannot_be_read(tmp_path, head):
    out, writes = post(tmp_path, head=head, HEAD_SHA="aaaaaaa1")
    assert len(writes) == 1
    assert "::warning::could not read the pr head" in out


# --- name.sh ------------------------------------------------------------------


@pytest.mark.parametrize("name", ["", "smoke", "ci-rock-crafter", "a.b_c-1", "A9"])
def test_name_accepted(name):
    proc = run(NAME, NAME=name)
    assert (proc.returncode, proc.stdout) == (0, "")


@pytest.mark.parametrize(
    "name", ["a b", "a/b", "a:b", "a`b", 'a"b', "a\nb", "a*", "caf\xe9", " ", "a\\b"]
)
def test_name_rejected(name):
    proc = run(NAME, NAME=name)
    assert proc.returncode == 1
    assert proc.stdout.startswith("::error::name '")
    # one line, and never the raw value: it would reach the log as a command
    assert proc.stdout.count("\n") == 1
    shown = proc.stdout.split("'")[1]
    assert shown == re.sub(rb"[^A-Za-z0-9._-]", b"?", name.encode()).decode()


def test_name_unset_is_an_unnamed_call():
    assert run(NAME).returncode == 0


# --- pats.sh ------------------------------------------------------------------

PATS = ROOT / "actions" / "run" / "pats.sh"

FAKE_PATS = """#!/usr/bin/env bash
if [[ "$1" == list ]]; then
  echo "VECTOR  SUITE  AGENTS"
  echo "suites  smoke  1"
  echo "suites  slow   1"
  exit 0
fi
echo "$*" >> "$CALLS"
"""


def run_pats(tmp_path, **env):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "pats"
    fake.write_text(FAKE_PATS)
    fake.chmod(0o755)
    out, calls = tmp_path / "out", tmp_path / "calls"
    out.touch()
    calls.touch()
    proc = subprocess.run(
        ["bash", str(PATS)],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out), "CALLS": str(calls), **env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc, out.read_text().splitlines(), calls.read_text().splitlines()


@pytest.mark.parametrize("args", ["-S smoke -j -1", "--suite=slow", "-Ssmoke,slow", ""])
def test_pats_known_suites_run(tmp_path, args):
    _, out, calls = run_pats(tmp_path, SKIP_MISSING_SUITES="true", RUN_ARGS=args)
    assert "skipped=false" in out
    assert [c.split()[0] for c in calls] == ["init", "run", "score"]


@pytest.mark.parametrize("args", ["-S new -j -1", "--suite=new", "-S smoke,new"])
def test_pats_missing_suite_skips(tmp_path, args):
    proc, out, calls = run_pats(tmp_path, SKIP_MISSING_SUITES="true", RUN_ARGS=args)
    assert out == ["skipped=true"]
    assert calls == []
    assert "::warning::" in proc.stdout and "new" in proc.stdout


def test_pats_missing_suite_runs_without_skip(tmp_path):
    _, out, calls = run_pats(tmp_path, RUN_ARGS="-S new")
    assert "skipped=false" in out
    assert len(calls) == 3
