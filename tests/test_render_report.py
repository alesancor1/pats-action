import copy
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "actions" / "report"))

import render_report as rr  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "report.json"


@pytest.fixture
def report():
    return json.loads(FIXTURE.read_text())


def test_header(report):
    md = rr.render(report)
    assert md.startswith("### pats report\n")
    assert "`acme/skills` @ `0123456789ab`" in md
    assert "pats `0.7.6`" in md
    assert "[workflow run](https://github.com/acme/skills/actions/runs/1)" in md
    assert "[!WARNING]" not in md


def test_score_table(report):
    md = rr.render(report)
    assert "**overall:** :yellow_circle: **0.76**" in md
    assert "| task | a1 | a2 |" in md
    # worst-first; missing a2/t2 cell is a dash.
    assert "| t2 | :red_circle: 0.25 | - |" in md
    assert md.index("| t2 |") < md.index("| t1 |")
    assert "| **avg** | :yellow_circle: 0.62 | :green_circle: 0.90 |" in md


def test_breakdown_and_stats(report):
    md = rr.render(report)
    assert "| a1/t2 | s2 | :red_circle: 0.00 |" in md
    assert "| a1/t1 | ok | 12.3s | 4 | 100 | 50 | $0.010 | 3 | - |" in md
    assert "| a2/t1 | :x: nonzero | 3.0s | - | - | - | - | - | evil.example |" in md


def test_failed_run_without_scores(report):
    r = copy.deepcopy(report)
    r.update(scores=None, pairs=[], run_exit_code=1, score_exit_code=None, run_name=None)
    md = rr.render(r)
    assert "`pats run` exited 1, `pats score` exited n/a" in md
    assert "_no scores: pats produced no scored run._" in md


def test_escapes_pipes(report):
    r = copy.deepcopy(report)
    r["scores"]["per_pair"] = {"a|b/t": 1.0}
    r["scores"]["per_agent"] = {"a|b": 1.0}
    r["scores"]["cells"] = []
    assert "| task | a\\|b |" in rr.render(r)


def test_rejects_unknown_schema(report):
    report["schema_version"] = 2
    with pytest.raises(ValueError):
        rr.render(report)


def test_truncate():
    out = rr.truncate("x" * 1000, 200)
    assert len(out) == 200
    assert out.endswith("_report truncated; see the workflow artifacts for the full run._\n")


def test_main_writes_outputs(tmp_path, monkeypatch):
    gh_out = tmp_path / "gh_out"
    md = tmp_path / "out.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    assert rr.main([str(FIXTURE), "-o", str(md)]) == 0
    assert md.read_text().startswith("### pats report\n")
    assert f"overall=0.7625\nmarkdown={md}\n" == gh_out.read_text()
