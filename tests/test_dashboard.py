"""Regressions for dashboard calendar semantics and missing-data presentation."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

APP = Path(__file__).resolve().parents[1] / "src/miband6/web/static/app.js"


def summary(health=None, activity=None, goal=8000):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for frontend calculation checks")
    src = APP.read_text()
    function = src[src.index("function overviewSummary("):src.index("async function loadOverview(")]
    # Supply the same calendar helper from the application, not a second implementation.
    start = src.index("const shiftDate =")
    helper = src[start:src.index("\n};", start) + 3]
    args = json.dumps([health, activity, goal, "2026-11-03"])
    code = "const pad = n => String(n).padStart(2, '0');\n" + helper + function
    code += "\nconsole.log(JSON.stringify(overviewSummary(..." + args + ")));"
    return json.loads(subprocess.check_output([node, "-e", code], text=True))


def test_dashboard_does_not_show_yesterdays_vitals_as_today():
    result = summary({"date": "2026-11-02", "has_data": True,
                      "day": {"steps": 9000, "hr": [[100, 72]]},
                      "insights": {"readiness": {"score": 90}}})
    assert result["steps"] is None
    assert result["pct"] is None
    assert result["streak"] is None
    assert "day" not in result
    assert "readiness" not in result


def test_streak_requires_consecutive_calendar_dates():
    result = summary({"date": "2026-11-03", "has_data": True, "day": {"steps": 300},
                      "steps_days": [{"date": "2026-11-02", "steps": 9000},
                                     {"date": "2026-10-31", "steps": 9500}]})
    assert result["streak"] == 1  # Missing November 1 cannot be bridged.
    assert result["steps"] == 300


def test_live_steps_are_not_replaced_by_older_sync_and_progress_is_capped():
    result = summary({"date": "2026-11-03", "has_data": True, "day": {"steps": 1000},
                      "steps_days": [{"date": "2026-11-02", "steps": 9000}]}, {"steps": 10000})
    assert result["steps"] == 10000
    assert result["pct"] == 100
    assert result["streak"] == 2


def test_no_measurement_is_not_zero_and_zero_readiness_is_preserved():
    result = summary({"date": "2026-11-03", "has_data": False, "day": {"steps": 0},
                      "insights": {"readiness": {"score": 0}}})
    assert result["steps"] is None
    assert result["readiness"]["score"] == 0
