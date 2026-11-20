import json
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


def test_pats_image_cache_dir_reaches_init_only(tmp_path):
    _, out, calls = run_pats(tmp_path, INIT_ARGS="-S smoke", IMAGE_CACHE_DIR="/cache")
    assert calls[0] == "init -S smoke --image-cache /cache"
    assert "--image-cache" not in calls[1] and "--image-cache" not in calls[2]
    assert "init-exit-code=0" in out


def test_pats_no_image_cache_by_default(tmp_path):
    _, _, calls = run_pats(tmp_path, INIT_ARGS="-S smoke")
    assert calls[0] == "init -S smoke"


# --- image-cache.sh -----------------------------------------------------------

IMAGE_CACHE = ROOT / "actions" / "run" / "image-cache.sh"

A1, A2, A3 = (f"pats-img-{c * 24}" for c in "abc")

FAKE_IMAGE_PATS = """#!/usr/bin/env bash
echo "${PATS_VERSION:-1.3.0 @ abc}"
"""

# `lxc project list` prints $PROJECTS, `lxc image list` $IMAGES; `lxc image
# export <alias> <base>` writes <base>.tar.zst and logs the alias to $EXPORTS.
# LXC_DOWN fails every call.
FAKE_LXC = """#!/usr/bin/env bash
[ -z "${LXC_DOWN:-}" ] || exit 1
case "$1 $2" in
  "project list") printf '%s' "$PROJECTS" ;;
  "image list") printf '%s' "$IMAGES" ;;
  "image export") echo "$3" >> "$EXPORTS"; touch "$4.tar.zst" ;;
esac
"""
PATS_PROJECT = json.dumps([{"name": "default"}, {"name": "pats"}])


def image_cache(tmp_path, cmd, images=(), ok=True, **env):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, text in (("pats", FAKE_IMAGE_PATS), ("lxc", FAKE_LXC)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    out, exports = tmp_path / "out", tmp_path / "exports"
    out.write_text("")
    exports.write_text("")
    listing = json.dumps([{"aliases": [{"name": a} for a in names]} for names in images])
    proc = subprocess.run(
        ["bash", str(IMAGE_CACHE), cmd],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "GITHUB_OUTPUT": str(out),
            "EXPORTS": str(exports),
            "IMAGES": listing,
            "PROJECTS": PATS_PROJECT,
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (proc.returncode == 0) == ok, proc.stderr
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines())
    return outputs, exports.read_text().split()


def test_image_cache_prepare_makes_the_dir(tmp_path):
    outputs, _ = image_cache(tmp_path, "prepare")
    assert outputs["dir"] == str(tmp_path / "pats-image-cache")
    assert (tmp_path / "pats-image-cache").is_dir()
    assert re.fullmatch(r"pats-images-[0-9a-f]{12}-[0-9a-f]{12}-", outputs["prefix"])


def test_image_cache_prefix_follows_version_and_init_args(tmp_path):
    def prefix(**env):
        return image_cache(tmp_path, "prepare", **env)[0]["prefix"]

    base = prefix(INIT_ARGS="-S rock")
    assert prefix(INIT_ARGS="-S rock") == base
    assert prefix(INIT_ARGS="-S smoke") != base
    assert prefix(INIT_ARGS="-S rock", PATS_VERSION="1.4.0 @ def") != base


def export(tmp_path, images, **env):
    cache = tmp_path / "cache"
    cache.mkdir(exist_ok=True)
    env = {"GITHUB_RUN_ID": "7", "GITHUB_RUN_ATTEMPT": "1", **env}
    return image_cache(
        tmp_path, "export", images, IMAGE_CACHE_DIR=str(cache), IMAGE_CACHE_PREFIX="p-", **env
    )


def test_image_cache_key_names_the_run(tmp_path):
    outputs, _ = export(tmp_path, [[A1]], GITHUB_RUN_ID="42", GITHUB_RUN_ATTEMPT="3")
    assert re.fullmatch(r"p-[0-9a-f]{12}-42-3", outputs["key"])


def test_image_cache_set_seen_before_is_saved_again(tmp_path):
    # a -> b -> a: the restore matches b, the newest, so a is saved under a new key.
    a, _ = export(tmp_path, [[A1]], GITHUB_RUN_ID="1")
    b, _ = export(tmp_path, [[A2]], GITHUB_RUN_ID="2", IMAGE_CACHE_MATCHED_KEY=a["key"])
    again, _ = export(tmp_path, [[A1]], GITHUB_RUN_ID="3", IMAGE_CACHE_MATCHED_KEY=b["key"])
    assert b["changed"] == again["changed"] == "true"
    assert again["key"] != a["key"]


def test_image_cache_no_pats_project_saves_nothing(tmp_path):
    # an init that made only docker sandboxes leaves lxd without a pats project.
    outputs, exports = export(tmp_path, [[A1]], PROJECTS=json.dumps([{"name": "default"}]))
    assert outputs["changed"] == "false" and exports == []


def test_image_cache_failed_list_keeps_the_dir(tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / f"{A1}.tar.zst").touch()
    outputs, _ = image_cache(
        tmp_path, "export", [[A1]], ok=False, LXC_DOWN="1",
        IMAGE_CACHE_DIR=str(tmp_path / "cache"), IMAGE_CACHE_PREFIX="p-",
    )
    assert outputs == {}
    assert (tmp_path / "cache" / f"{A1}.tar.zst").exists()


def test_image_cache_export_writes_new_images_only(tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / f"{A1}.tar.zst").touch()
    outputs, exports = export(tmp_path, [[A1], [A2, "my-rock"], ["not-pats"]])
    assert exports == [A2]
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == [f"{A1}.tar.zst", f"{A2}.tar.zst"]
    assert outputs["changed"] == "true"


def test_image_cache_export_drops_images_the_server_lacks(tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / f"{A3}.tar.zst").touch()
    export(tmp_path, [[A1]])
    assert [p.name for p in (tmp_path / "cache").iterdir()] == [f"{A1}.tar.zst"]


def test_image_cache_key_is_the_image_set(tmp_path):
    one, _ = export(tmp_path, [[A1], [A2]])
    two, _ = export(tmp_path, [[A2], [A1]])
    three, _ = export(tmp_path, [[A1]])
    assert one["key"] == two["key"] != three["key"]
    assert one["key"].startswith("p-")


def test_image_cache_unchanged_set_is_not_saved(tmp_path):
    first, _ = export(tmp_path, [[A1]])
    again, _ = export(tmp_path, [[A1]], IMAGE_CACHE_MATCHED_KEY=first["key"])
    assert again["changed"] == "false"


def test_image_cache_nothing_to_save_without_images(tmp_path):
    outputs, exports = export(tmp_path, [])
    assert outputs["changed"] == "false" and exports == []
