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


def test_comment_unnamed_heading():
    lines = body()
    assert lines[0] == "<!-- pats-comment:acme/skills/tests -->"
    assert lines[1].startswith("## ") and lines[1].endswith(" pats evaluation")


def test_comment_named_heading():
    lines = body(NAME="ci-rock-crafter")
    assert lines[1].endswith(" pats evaluation: `ci-rock-crafter`")


def test_comment_name_changes_the_heading_only():
    # the marker is what finds the sticky comment: the name must not move it
    plain, named = body(), body(NAME="smoke")
    assert [i for i, (a, b) in enumerate(zip(plain, named)) if a != b] == [1]
    assert len(plain) == len(named)


@pytest.mark.parametrize(
    "name",
    ["a`b", "<script>alert(1)</script>", "a\nb", "a & b", "## heading", "a|b"],
)
def test_comment_hostile_name_stays_one_code_span(name):
    plain, named = body(), body(NAME=name)
    assert len(named) == len(plain)
    shown = named[1].split(" pats evaluation: ", 1)[1]
    assert shown.startswith("`") and shown.endswith("`")
    assert set(shown[1:-1]) <= set("abcdefghijklmnopqrstuvwxyz1()_.-")


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
