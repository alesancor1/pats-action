#!/usr/bin/env python3
"""Stage the logs of a pats run for upload as an artifact.

copies the run dir (per pair: the agent's transcript, the step logs, the
egress log, `metadata.json` and what `collect` kept for the scorers) to
OUT/run, and the `pats init` logs to OUT/init. only regular files are copied:
a link or a special file is counted and left behind, and so is a dir given
through a link.

the value of each harness credential in the env (CREDENTIALS) is replaced by
its name in the copies. only as written: an encoded value is not found.

usage: logs.py -o OUT [--run-dir DIR] [--init-dir DIR]

a dir that is not given, empty or missing is skipped. when anything was copied
and GITHUB_OUTPUT is set, exports `dir` (OUT, absolute) as a step output.
a file or dir that could not be copied is a warning, not a failure.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

# the names pats reads its harness credentials under.
CREDENTIALS = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "COPILOT_GITHUB_TOKEN",
)


@dataclass
class Stats:
    copied: int = 0
    skipped: int = 0  # links and special files
    failed: int = 0  # could not be read or written
    replaced: dict[str, int] = field(default_factory=dict)  # credential -> files


def credentials(env: dict[str, str]) -> list[tuple[str, bytes]]:
    """(name, value) of each credential that is set."""
    found = [(name, env.get(name, "").strip().encode()) for name in CREDENTIALS]
    return [c for c in found if c[1]]


def scrub(data: bytes, creds: list[tuple[str, bytes]]) -> tuple[bytes, list[str]]:
    """data with every credential value replaced by `[NAME]`, and the names found.

    values may overlap or hold one another, so the spans are found in the
    data as it was and merged: replacing one value at a time could cut another
    in two and leave its tail.
    """
    spans = []
    for name, value in creds:
        at = data.find(value)
        while at != -1:
            spans.append((at, at + len(value), name))
            at = data.find(value, at + 1)
    if not spans:
        return data, []
    spans.sort()
    out, found, pos, i = [], [], 0, 0
    while i < len(spans):
        start, stop, _ = spans[i]
        names = []
        while i < len(spans) and spans[i][0] <= stop:
            stop = max(stop, spans[i][1])
            if spans[i][2] not in names:
                names.append(spans[i][2])
            i += 1
        out += [data[pos:start], "".join(f"[{n}]" for n in names).encode()]
        found += [n for n in names if n not in found]
        pos = stop
    out.append(data[pos:])
    return b"".join(out), found


def linked(src: Path) -> bool:
    """whether src is a link, or reached from the cwd through one."""
    src = Path(os.path.abspath(src))
    try:
        below = src.relative_to(Path.cwd()).parts
    except ValueError:
        return src.is_symlink()
    return any(Path(*below[: i + 1]).is_symlink() for i in range(len(below)))


def read_regular(path: Path) -> bytes | None:
    """the file's bytes, or None for anything but a regular file. never follows a link."""
    if not stat.S_ISREG(path.lstat().st_mode):
        return None
    # the lstat and the open are two looks at the path: don't follow or block
    # on whatever is there by the second.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            return None
        return fh.read()


def copy_tree(src: Path, dst: Path, creds: list[tuple[str, bytes]], stats: Stats) -> None:
    def failed(_: OSError) -> None:
        stats.failed += 1

    for root, dirs, files in os.walk(src, onerror=failed):
        here = Path(root)
        # os.walk lists a linked dir but does not walk into it.
        stats.skipped += sum((here / d).is_symlink() for d in dirs)
        for name in files:
            try:
                data = read_regular(here / name)
                if data is None:
                    stats.skipped += 1
                    continue
                data, found = scrub(data, creds)
                out = dst / here.relative_to(src) / name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            except (OSError, MemoryError):  # a file is held whole
                stats.failed += 1
                continue
            for cred in found:
                stats.replaced[cred] = stats.replaced.get(cred, 0) + 1
            stats.copied += 1


def stage(out: Path, trees: dict[str, str | None], env: dict[str, str]) -> Stats:
    """copy each tree to out/<name>, replacing what an earlier call left there."""
    stats = Stats()
    creds = credentials(env)
    for name, src in trees.items():
        dst = out / name
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        elif dst.exists():
            shutil.rmtree(dst)
        if not src or not Path(src).is_dir():
            continue
        if linked(Path(src)):
            stats.skipped += 1
            continue
        copy_tree(Path(src), dst, creds, stats)
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", required=True, help="dir to stage into")
    ap.add_argument("--run-dir", default="", help="the pats run dir")
    ap.add_argument("--init-dir", default="", help="the `pats init` logs, .pats/init")
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    stats = stage(out, {"run": args.run_dir, "init": args.init_dir}, dict(os.environ))

    if stats.skipped:
        print(f"logs: left {stats.skipped} link(s) / special file(s) behind")
    if stats.failed:
        print(f"::warning::logs: {stats.failed} file(s) or dir(s) could not be copied")
    for cred, n in sorted(stats.replaced.items()):
        print(f"logs: replaced the value of {cred} in {n} file(s)")
    if not stats.copied:
        print("logs: nothing to stage")
        return 0
    print(f"logs: {stats.copied} file(s) staged in {out}")
    if gh_out := os.environ.get("GITHUB_OUTPUT"):
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"dir={out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
