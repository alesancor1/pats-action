#!/usr/bin/env python3
"""Render a pats-action json report (schema_version 1) as github markdown.

usage: render_report.py REPORT_JSON [-o OUT_MD] [--title TITLE] [--max-chars N] [--step-summary]

prints/writes the markdown and, when GITHUB_OUTPUT is set, exports `overall`
and `markdown` (the output path) as step outputs. --step-summary also appends
it to $GITHUB_STEP_SUMMARY.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any

SCHEMA_VERSION = 1
# github caps comment bodies at 65536 chars; leave room for a marker/header.
DEFAULT_MAX_CHARS = 64000


def icon(score: float) -> str:
    if score >= 0.8:
        return ":green_circle:"
    if score >= 0.5:
        return ":yellow_circle:"
    return ":red_circle:"


def fmt_score(score: float | None, bold: bool = False) -> str:
    if score is None:
        return "-"
    num = f"**{score:.2f}**" if bold else f"{score:.2f}"
    return f"{icon(score)} {num}"


def esc(s: Any) -> str:
    return str(s).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def score_table(scores: dict) -> list[str]:
    per_pair: dict[str, float] = scores.get("per_pair") or {}
    per_agent: dict[str, float] = scores.get("per_agent") or {}
    agents = sorted(per_agent) or sorted({k.split("/", 1)[0] for k in per_pair})
    tasks = {k.split("/", 1)[1] for k in per_pair if "/" in k}
    if not tasks:
        return ["_no scores recorded._"]

    # worst-first, like pats' terminal report: min cell across agents.
    def worst(task: str) -> float:
        vals = [per_pair[f"{a}/{task}"] for a in agents if f"{a}/{task}" in per_pair]
        return min(vals) if vals else math.inf

    ordered = sorted(tasks, key=lambda t: (worst(t), t))
    lines = [
        "| task | " + " | ".join(esc(a) for a in agents) + " |",
        "|---|" + "---:|" * len(agents),
    ]
    for t in ordered:
        cells = [fmt_score(per_pair.get(f"{a}/{t}")) for a in agents]
        lines.append(f"| {esc(t)} | " + " | ".join(cells) + " |")
    if len(ordered) > 1:
        cells = [fmt_score(per_agent.get(a)) for a in agents]
        lines.append("| **avg** | " + " | ".join(cells) + " |")
    return lines


def breakdown(scores: dict) -> list[str]:
    per_pair: dict[str, float] = scores.get("per_pair") or {}
    cells = scores.get("cells") or []
    if not cells:
        return []
    cells = sorted(
        cells,
        key=lambda c: (
            per_pair.get(f"{c['agent']}/{c['task']}", 0.0),
            f"{c['agent']}/{c['task']}",
            c["score"],
            c["scorer"],
        ),
    )
    lines = ["<details><summary>scorer breakdown</summary>", "",
             "| pair | scorer | score |", "|---|---|---:|"]
    for c in cells:
        lines.append(f"| {esc(c['agent'])}/{esc(c['task'])} | {esc(c['scorer'])} | {fmt_score(c['score'])} |")
    lines += ["", "</details>"]
    return lines


def stats(pairs: list[dict]) -> list[str]:
    if not pairs:
        return []
    lines = ["<details><summary>run stats</summary>", "",
             "| pair | status | time | turns | in | out | cost | tools | denied egress |",
             "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    tot_time = tot_cost = 0.0
    for p in sorted(pairs, key=lambda p: (p.get("agent", ""), p.get("task", ""))):
        s = p.get("summary") or {}
        turns = inp = out = cost = tools = "-"
        if s:
            turns = str(s.get("num_turns", 0))
            inp = str(s.get("input_tokens", 0))
            out = str(s.get("output_tokens", 0))
            tools = str(sum((s.get("tools") or {}).values()))
            if s.get("has_cost"):
                cost = f"${s.get('cost_usd', 0.0):.3f}"
            tot_cost += s.get("cost_usd", 0.0)
        dur = p.get("duration_s", 0.0)
        tot_time += dur
        status = p.get("status", "?")
        if status != "ok":
            status = f":x: {status}"
        denied = ", ".join(p.get("denied_egress") or []) or "-"
        lines.append(
            f"| {esc(p.get('agent', '?'))}/{esc(p.get('task', '?'))} | {esc(status)} | {dur:.1f}s "
            f"| {turns} | {inp} | {out} | {cost} | {tools} | {esc(denied)} |"
        )
    lines.append(f"| **total** | | {tot_time:.1f}s | | | | ${tot_cost:.3f} | | |")
    lines += ["", "</details>"]
    return lines


def render(report: dict, title: str = "pats report") -> str:
    version = report.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported report schema_version {version!r} (want {SCHEMA_VERSION})")

    meta = [f"`{report.get('repository', '?')}` @ `{(report.get('sha') or '?')[:12]}`"]
    if report.get("pats_version"):
        meta.append(f"pats `{report['pats_version']}`")
    if report.get("workflow_run_url"):
        meta.append(f"[workflow run]({report['workflow_run_url']})")

    lines = [f"### {title}", "", " &middot; ".join(meta), ""]

    run_rc, score_rc = report.get("run_exit_code"), report.get("score_exit_code")
    if run_rc not in (0, None) or score_rc not in (0, None) or run_rc is None:
        lines += ["> [!WARNING]",
                  f"> `pats run` exited {run_rc if run_rc is not None else 'n/a'}, "
                  f"`pats score` exited {score_rc if score_rc is not None else 'n/a'} -- see the workflow log.",
                  ""]

    scores = report.get("scores")
    if scores:
        run = f"**run:** `{report['run_name']}` &nbsp; " if report.get("run_name") else ""
        lines += [f"{run}**overall:** {fmt_score(scores.get('overall'), bold=True)}", ""]
        lines += score_table(scores)
        bd = breakdown(scores)
        if bd:
            lines += [""] + bd
    else:
        lines.append("_no scores: pats produced no scored run._")

    st = stats(report.get("pairs") or [])
    if st:
        lines += [""] + st
    return "\n".join(lines) + "\n"


def truncate(md: str, max_chars: int) -> str:
    if len(md) <= max_chars:
        return md
    note = "\n\n_report truncated; see the workflow artifacts for the full run._\n"
    return md[: max_chars - len(note)] + note


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report")
    ap.add_argument("-o", "--output")
    ap.add_argument("--title", default="pats report")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    ap.add_argument("--step-summary", action="store_true", help="also append to $GITHUB_STEP_SUMMARY")
    args = ap.parse_args(argv)

    with open(args.report, encoding="utf-8") as f:
        report = json.load(f)
    md = truncate(render(report, args.title), args.max_chars)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        sys.stdout.write(md)

    if args.step_summary and (summary := os.environ.get("GITHUB_STEP_SUMMARY")):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(md)

    if gh_out := os.environ.get("GITHUB_OUTPUT"):
        overall = (report.get("scores") or {}).get("overall")
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"overall={'' if overall is None else overall}\n")
            if args.output:
                f.write(f"markdown={os.path.abspath(args.output)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
