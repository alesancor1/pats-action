import os
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMMENT = ROOT / "actions" / "comment" / "comment.sh"
NAME = ROOT / ".github" / "scripts" / "name.sh"
LOGS = ROOT / "actions" / "run" / "logs.sh"

ENV = {
    "KEY": "acme/skills/tests",
    "GITHUB_REPOSITORY": "acme/skills",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_RUN_ID": "1",
    "BASE_REF": "main",
    "OVERALL": "0.80",
    "BASE_OVERALL": "0.70",
}


def run(script, *args, cwd=None, **env):
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=cwd,
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


# --- logs.sh ------------------------------------------------------------------

# shaped like nothing real: a key-like fixture trips secret scanners.
KEY = "fixture-value-0123456789"


def stage(tmp_path, **env):
    proc = run(
        LOGS, cwd=tmp_path, RUNNER_TEMP=str(tmp_path / "tmp"), GITHUB_OUTPUT=str(tmp_path / "out"), **env
    )
    staged = tmp_path / "tmp" / "pats-logs"
    files = {str(p.relative_to(staged)): p.read_bytes() for p in staged.rglob("*") if not p.is_dir()}
    return proc, files, (tmp_path / "out").read_text() if (tmp_path / "out").exists() else ""


def test_logs_stages_regular_files_without_the_credentials(tmp_path):
    (tmp_path / "secret").write_text("not for the artifact\n")
    (tmp_path / ".pats" / "init").mkdir(parents=True)
    (tmp_path / ".pats" / "init" / "steps.log").write_text("built\n")
    pair = tmp_path / ".pats" / "runs" / "001" / "agent" / "task"
    pair.mkdir(parents=True)
    (pair / "stdout.log").write_bytes(f"key {KEY} again {KEY}\n\xff".encode("latin-1"))
    (pair / ".hidden").write_text("kept\n")
    (pair / "link").symlink_to(tmp_path / "secret")
    (pair / "linked-dir").symlink_to(tmp_path, target_is_directory=True)
    os.mkfifo(pair / "pipe")

    proc, files, out = stage(
        tmp_path, RUN_DIR=str(pair.parent.parent), OPENROUTER_API_KEY=f" {KEY}\n", ANTHROPIC_API_KEY=""
    )
    assert proc.returncode == 0, proc.stderr
    assert files == {
        "init/steps.log": b"built\n",
        "run/agent/task/.hidden": b"kept\n",
        "run/agent/task/stdout.log": b"key [OPENROUTER_API_KEY] again [OPENROUTER_API_KEY]\n\xff",
    }
    assert out == f"dir={tmp_path}/tmp/pats-logs\n"
    assert KEY in (pair / "stdout.log").read_text("latin-1")  # the run dir is not touched


def test_logs_does_not_follow_a_linked_run_dir(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "id_key").write_text("not for the artifact\n")
    (tmp_path / "run").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    proc, files, out = stage(tmp_path, RUN_DIR=str(tmp_path / "run"))
    assert (proc.returncode, files, out) == (0, {}, "")


@pytest.mark.parametrize("run_dir", ["", "no/such/dir"])
def test_logs_with_nothing_to_stage_exports_nothing(tmp_path, run_dir):
    proc, files, out = stage(tmp_path, RUN_DIR=run_dir)
    assert (proc.returncode, files, out) == (0, {}, "")
