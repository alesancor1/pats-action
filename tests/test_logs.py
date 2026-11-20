import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "actions" / "run" / "logs.py"
sys.path.insert(0, str(SCRIPT.parent))

import logs  # noqa: E402

# shaped like nothing real: a key-like fixture trips secret scanners.
KEY = "fixture-value-0123456789"


@pytest.fixture
def run_dir(tmp_path):
    pair = tmp_path / "runs" / "001-run" / "agent" / "task"
    pair.mkdir(parents=True)
    (pair / "stdout.log").write_text("turn 1\nturn 2\n")
    (pair / "metadata.json").write_text('{"status": "ok"}\n')
    (pair / ".hidden").write_text("kept\n")
    (pair.parent.parent / "scores.json").write_text("{}\n")
    return tmp_path / "runs" / "001-run"


@pytest.fixture
def init_dir(tmp_path):
    d = tmp_path / ".pats" / "init"
    d.mkdir(parents=True)
    (d / "steps.log").write_text("built\n")
    return d


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if not p.is_dir())


def stage(out, run_dir=None, init_dir=None, **env):
    trees = {"run": run_dir and str(run_dir), "init": init_dir and str(init_dir)}
    return logs.stage(out, trees, env)


def test_copies_the_run_dir_and_the_init_logs(tmp_path, run_dir, init_dir):
    out = tmp_path / "out"
    stats = stage(out, run_dir, init_dir)
    assert tree(out) == [
        "init/steps.log",
        "run/agent/task/.hidden",
        "run/agent/task/metadata.json",
        "run/agent/task/stdout.log",
        "run/scores.json",
    ]
    assert (out / "run/agent/task/stdout.log").read_text() == "turn 1\nturn 2\n"
    assert (stats.copied, stats.skipped, stats.failed, stats.replaced) == (5, 0, 0, {})


@pytest.mark.parametrize("missing", [None, "", "no/such/dir"])
def test_a_dir_that_is_not_there_is_skipped(tmp_path, init_dir, missing):
    out = tmp_path / "out"
    stats = stage(out, missing, init_dir)
    assert tree(out) == ["init/steps.log"]
    assert stats.copied == 1


def test_links_are_left_behind(tmp_path, run_dir):
    secret = tmp_path / "host-secret"
    secret.write_text("not for the artifact\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "inner").write_text("not for the artifact\n")
    pair = run_dir / "agent" / "task"
    (pair / "link").symlink_to(secret)
    (pair / "dangling").symlink_to(tmp_path / "nowhere")
    (pair / "linked-dir").symlink_to(elsewhere, target_is_directory=True)

    out = tmp_path / "out"
    stats = stage(out, run_dir)
    assert stats.skipped == 3
    assert not any("link" in name or "dangling" in name for name in tree(out))
    assert "not for the artifact" not in "".join(
        p.read_text() for p in out.rglob("*") if p.is_file()
    )


def test_a_dir_given_as_a_link_is_left_behind(tmp_path, run_dir, init_dir):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "id_key").write_text("not for the artifact\n")
    link = tmp_path / "linked-run"
    link.symlink_to(elsewhere, target_is_directory=True)
    out = tmp_path / "out"
    stats = stage(out, link, init_dir)
    assert tree(out) == ["init/steps.log"]
    assert stats.skipped == 1


def test_a_dir_reached_through_a_link_is_left_behind(tmp_path, monkeypatch):
    # .pats itself is the link: .pats/init is then someone else's dir
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "init").mkdir(parents=True)
    (elsewhere / "init" / "runner.cred").write_text("not for the artifact\n")
    work = tmp_path / "work"
    work.mkdir()
    (work / ".pats").symlink_to(elsewhere, target_is_directory=True)
    monkeypatch.chdir(work)
    out = tmp_path / "out"
    stats = stage(out, None, ".pats/init")
    assert not out.exists() or tree(out) == []
    assert (stats.copied, stats.skipped) == (0, 1)


def test_a_relative_dir_with_no_link_on_the_way_is_copied(tmp_path, init_dir, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out"
    stats = stage(out, None, ".pats/init")
    assert tree(out) == ["init/steps.log"]
    assert stats.skipped == 0


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes anywhere")
def test_a_file_that_cannot_be_written_is_counted(tmp_path, run_dir):
    out = tmp_path / "out"
    out.mkdir()
    out.chmod(0o500)
    try:
        stats = stage(out, run_dir)
    finally:
        out.chmod(0o700)
    assert (stats.copied, stats.failed) == (0, 4)


def test_a_fifo_is_left_behind_without_blocking(tmp_path, run_dir):
    os.mkfifo(run_dir / "agent" / "task" / "pipe")
    out = tmp_path / "out"
    stats = stage(out, run_dir)
    assert stats.skipped == 1
    assert "run/agent/task/pipe" not in tree(out)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads anything")
def test_an_unreadable_file_is_counted_and_the_rest_copied(tmp_path, run_dir):
    locked = run_dir / "agent" / "task" / "locked"
    locked.write_text("x")
    locked.chmod(0)
    out = tmp_path / "out"
    stats = stage(out, run_dir)
    assert (stats.copied, stats.failed) == (4, 1)
    assert "run/agent/task/locked" not in tree(out)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads anything")
def test_an_unreadable_dir_is_counted_and_the_rest_copied(tmp_path, run_dir):
    locked = run_dir / "agent" / "task" / "locked"
    locked.mkdir()
    (locked / "inner.log").write_text("x")
    locked.chmod(0)
    try:
        out = tmp_path / "out"
        stats = stage(out, run_dir)
    finally:
        locked.chmod(0o700)  # or pytest can't clear tmp_path
    assert (stats.copied, stats.failed) == (4, 1)
    assert not (out / "run/agent/task/locked").exists()


def test_a_file_too_big_to_read_is_counted_and_the_rest_copied(tmp_path, run_dir, monkeypatch):
    real = logs.read_regular

    def read(path):
        if path.name == "stdout.log":
            raise MemoryError
        return real(path)

    monkeypatch.setattr(logs, "read_regular", read)
    out = tmp_path / "out"
    stats = stage(out, run_dir)
    assert (stats.copied, stats.failed) == (3, 1)


def test_a_credential_is_replaced_by_its_name(tmp_path, run_dir):
    pair = run_dir / "agent" / "task"
    (pair / "stdout.log").write_text(f"OPENROUTER_API_KEY={KEY}\nagain {KEY}\n")
    (pair / "blob.bin").write_bytes(b"\x00\xff" + KEY.encode() + b"\xfe\n")

    out = tmp_path / "out"
    stats = stage(out, run_dir, OPENROUTER_API_KEY=KEY)
    copy = out / "run/agent/task"
    assert copy.joinpath("stdout.log").read_text() == (
        "OPENROUTER_API_KEY=[OPENROUTER_API_KEY]\nagain [OPENROUTER_API_KEY]\n"
    )
    assert copy.joinpath("blob.bin").read_bytes() == b"\x00\xff[OPENROUTER_API_KEY]\xfe\n"
    assert stats.replaced == {"OPENROUTER_API_KEY": 2}
    # the run dir itself is not touched
    assert KEY in pair.joinpath("stdout.log").read_text()


def test_a_credential_is_matched_without_its_surrounding_whitespace(tmp_path, run_dir):
    (run_dir / "agent" / "task" / "stdout.log").write_text(f"key {KEY} end\n")
    out = tmp_path / "out"
    stage(out, run_dir, ANTHROPIC_API_KEY=f"  {KEY}\n")
    assert (out / "run/agent/task/stdout.log").read_text() == "key [ANTHROPIC_API_KEY] end\n"


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_an_empty_credential_changes_nothing(tmp_path, run_dir, value):
    out = tmp_path / "out"
    stats = stage(out, run_dir, OPENROUTER_API_KEY=value)
    assert (out / "run/agent/task/stdout.log").read_text() == "turn 1\nturn 2\n"
    assert stats.replaced == {}


def test_a_credential_holding_another_leaves_no_tail(tmp_path, run_dir):
    long = KEY + "-and-more"
    (run_dir / "agent" / "task" / "stdout.log").write_text(f"{long}\n{KEY}\n")
    out = tmp_path / "out"
    stage(out, run_dir, ANTHROPIC_API_KEY=KEY, OPENROUTER_API_KEY=long)
    assert (out / "run/agent/task/stdout.log").read_text() == (
        "[ANTHROPIC_API_KEY][OPENROUTER_API_KEY]\n[ANTHROPIC_API_KEY]\n"
    )


def test_a_credential_inside_another_leaves_no_tail(tmp_path, run_dir):
    long = "pre-" + KEY + "-post"
    (run_dir / "agent" / "task" / "stdout.log").write_text(f"<{long}>\n")
    out = tmp_path / "out"
    stage(out, run_dir, ANTHROPIC_API_KEY=KEY, OPENROUTER_API_KEY=long)
    assert (out / "run/agent/task/stdout.log").read_text() == (
        "<[OPENROUTER_API_KEY][ANTHROPIC_API_KEY]>\n"
    )


def test_credentials_that_overlap_leave_no_tail(tmp_path, run_dir):
    # replaced one at a time, the first would cut the second in two
    a, b = "sk-AAAA-BBBB", "BBBB-CCCC"
    (run_dir / "agent" / "task" / "stdout.log").write_text(f"x sk-AAAA-BBBB-CCCC y {b} z\n")
    out = tmp_path / "out"
    stats = stage(out, run_dir, ANTHROPIC_API_KEY=a, OPENROUTER_API_KEY=b)
    assert (out / "run/agent/task/stdout.log").read_text() == (
        "x [ANTHROPIC_API_KEY][OPENROUTER_API_KEY] y [OPENROUTER_API_KEY] z\n"
    )
    assert stats.replaced == {"ANTHROPIC_API_KEY": 1, "OPENROUTER_API_KEY": 1}


@pytest.mark.parametrize(
    ("data", "want"),
    [
        (b"", b""),
        (b"none", b"none"),
        (b"ab", b"[A]"),
        (b"abab", b"[A]"),  # touching spans are one
        (b"ab-ab", b"[A]-[A]"),
        (b"xabcx", b"x[A][B]x"),
        (b"bcab", b"[B][A]"),
        (b"aaa", b"[C]"),  # a value overlapping itself
        (b"\xffab\x00", b"\xff[A]\x00"),
    ],
)
def test_scrub_covers_every_byte_of_every_value(data, want):
    creds = [("A", b"ab"), ("B", b"bc"), ("C", b"aa")]
    got, found = logs.scrub(data, creds)
    assert got == want
    assert sorted(found) == [n for n in ("A", "B", "C") if f"[{n}]".encode() in want]


def test_only_the_harness_credentials_are_looked_for(tmp_path, run_dir):
    (run_dir / "agent" / "task" / "stdout.log").write_text("value-of-something-else\n")
    out = tmp_path / "out"
    stats = stage(out, run_dir, SOMETHING_ELSE="value-of-something-else")
    assert stats.replaced == {}


def test_an_earlier_call_leaves_nothing_behind(tmp_path, run_dir, init_dir):
    out = tmp_path / "out"
    (out / "run" / "old-agent").mkdir(parents=True)
    (out / "run" / "old-agent" / "stdout.log").write_text("stale\n")
    (out / "init").mkdir()
    (out / "init" / "old.log").write_text("stale\n")
    stage(out, run_dir, None)
    assert not any("old" in name for name in tree(out))
    assert not (out / "init").exists()


# --- the script, as the action runs it ----------------------------------------


def script(*args, cwd=None, **env):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        env={"PATH": os.environ["PATH"], **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_script_exports_the_staged_dir(tmp_path, run_dir, init_dir):
    # a relative -o still exports an absolute dir: the upload step runs elsewhere
    gh_out = tmp_path / "gh-output"
    out = tmp_path / "out"
    proc = script(
        "-o", "out", "--run-dir", str(run_dir), "--init-dir", str(init_dir),
        cwd=tmp_path, GITHUB_OUTPUT=str(gh_out), OPENROUTER_API_KEY=KEY,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert gh_out.read_text() == f"dir={out.resolve()}\n"
    assert f"logs: 5 file(s) staged in {out.resolve()}" in proc.stdout
    assert "::warning::" not in proc.stdout


def test_script_with_nothing_to_stage_exports_nothing(tmp_path):
    gh_out = tmp_path / "gh-output"
    proc = script(
        "-o", str(tmp_path / "out"), "--run-dir", "", "--init-dir", ".pats/init",
        GITHUB_OUTPUT=str(gh_out),
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "logs: nothing to stage\n"
    assert not gh_out.exists()


def test_script_says_what_it_replaced_but_never_the_value(tmp_path, run_dir):
    (run_dir / "agent" / "task" / "stdout.log").write_text(f"{KEY}\n")
    proc = script("-o", str(tmp_path / "out"), "--run-dir", str(run_dir), OPENROUTER_API_KEY=KEY)
    assert "logs: replaced the value of OPENROUTER_API_KEY in 1 file(s)" in proc.stdout
    assert KEY not in proc.stdout + proc.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads anything")
def test_script_warns_on_what_it_could_not_read(tmp_path, run_dir):
    locked = run_dir / "agent" / "task" / "locked"
    locked.write_text("x")
    locked.chmod(0)
    proc = script("-o", str(tmp_path / "out"), "--run-dir", str(run_dir))
    assert proc.returncode == 0
    assert "::warning::logs: 1 file(s) or dir(s) could not be copied" in proc.stdout


def test_script_needs_an_out_dir():
    proc = script("--run-dir", "x")
    assert proc.returncode == 2
    assert "usage: logs.py" in proc.stderr
