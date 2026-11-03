"""Quality gates preserve evidence and distinguish missing data from healthy readings."""
import sqlite3

import pytest

from miband6 import health as H
from miband6.healthdb import HealthDB
from miband6.telemetry import assess, sampling


def test_quality_does_not_hide_low_oxygen_or_invent_hrv():
    low = assess("spo2", 82, previous=(100, 98), timestamp=160)
    assert low["usable"] and low["status"] == "suspect"
    assert "abrupt_change" in low["flags"]
    assert not assess("spo2", 101)["usable"]
    assert not assess("stress", 101)["usable"]
    assert assess("stress", 0)["usable"]
    assert assess("hr", 0)["status"] == "missing"
    assert assess("hr", 255)["status"] == "missing"
    assert not assess("hr", 225)["usable"]
    assert assess("hr", 180, previous=(100, 60), timestamp=160)["status"] == "suspect"


def test_sampling_accounts_for_configured_cadence_and_never_interpolates():
    one = sampling([0, 60, 120, 240], 0, 300, expected_interval_seconds=60)
    assert one["coverage_ratio"] == .8 and one["missing_slots"] == 1
    five = sampling([0, 300, 600], 0, 900, expected_interval_seconds=300)
    assert five["coverage_ratio"] == 1 and five["missing_slots"] == 0
    assert sampling([0, 300], 0, 900)["coverage_ratio"] is None
    assert sampling([], 0, 900)["observed_median_interval_seconds"] is None
    assert sampling([0, 0, 60], 0, 120, expected_interval_seconds=60)["samples"] == 2


def test_invalid_values_retained_in_db_but_excluded_from_display(tmp_path):
    db = HealthDB(tmp_path / "health.db")
    t0, _ = H.day_bounds("2026-01-10")
    rows = [(t0 + i * 60, 1, 0, 0, hr, 0, 0, 0) for i, hr in enumerate([60, 225, 255])]
    db.add_activity(rows)
    db.add_activity(rows)
    db.add_stress([(t0, 101), (t0 + 60, 0)], auto=True)
    db.add_spo2([(t0, 120, False), (t0 + 60, 82, False)])
    result = db.summary("2026-01-10", hr_interval_minutes=1)
    assert db.samples(t0, t0 + 180) == rows
    assert result["day"]["hr"] == [[t0, 60]]
    assert result["day"]["stress"] == [[t0 + 60, 0, 1]]
    assert result["day"]["spo2"] == [[t0 + 60, 82, 0]]
    assert result["quality"]["hr"]["counts"] == {"valid": 1, "suspect": 0, "invalid": 1, "missing": 1}
    assert result["quality"]["hr"]["source"] == "band_processed_ppg"
    assert result["quality"]["hr"]["raw_rr_available"] is False
    assert db.db.execute("SELECT value FROM spo2 WHERE ts = ?", (t0,)).fetchone()[0] == 120
    db.close()


def test_failed_batch_rolls_back_and_cannot_leak_into_next_commit(tmp_path):
    db = HealthDB(tmp_path / "health.db")
    with pytest.raises(sqlite3.ProgrammingError):
        db.add_activity([(100, 1, 0, 1, 60, 0, 0, 0), (160, 1)])
    db.set_last("other_stream", 200)
    assert db.samples(0, 300) == []
    db.close()


def test_quality_rejects_nonfinite_values_and_counts_empty_window():
    for value in (None, float("nan"), float("inf"), True):
        assert assess("spo2", value)["status"] == "invalid"
    empty = sampling([], 0, 60, expected_interval_seconds=60)
    assert empty["coverage_ratio"] == 0 and empty["missing_slots"] == 1
    with pytest.raises(ValueError):
        sampling([], 0, 60, expected_interval_seconds=0)


def test_invalid_stress_does_not_change_analysis_or_readiness(tmp_path):
    db = HealthDB(tmp_path / "health.db")
    date = "2026-01-10"
    t0, _ = H.day_bounds(date)
    db.add_stress([(t0 - 60, 40)], auto=True)
    baseline = db.analysis(today=date)
    db.add_stress([(t0 - 120, 200)], auto=True)
    assert db.analysis(today=date) == baseline
    db.close()


def test_recovery_minimum_requires_five_contiguous_minutes():
    t0, _ = H.day_bounds("2026-01-10")
    sess = {"start": t0, "end": t0 + 60 * 60, "minutes": 60, "deep": 0, "rem": 0,
            "awake": 0, "stages": [[t0, t0 + 60 * 60, "light"]]}
    # Half the night is observed, but no five-minute contiguous window exists.
    sparse = {t0 + i * 60: (t0 + i * 60, 9, 0, 0, 60, 0, 0, 0) for i in range(0, 60, 2)}
    assert HealthDB._night(sess, sparse, "2026-01-10")["hr_low_at"] is None
    dense = {t0 + i * 60: (t0 + i * 60, 9, 0, 0, 60, 0, 0, 0) for i in range(60)}
    assert HealthDB._night(sess, dense, "2026-01-10")["hr_low_at"] == pytest.approx(2 / 60)


@pytest.mark.parametrize("minutes", [[0, 1, 2], [0, 5, 10], [0, 1, 40]])
def test_training_load_never_fills_unobserved_minutes(tmp_path, monkeypatch, minutes):
    from miband6 import insights as I
    db = HealthDB(tmp_path / "health.db")
    date = "2026-01-10"
    t0, _ = H.day_bounds(date)
    db.add_activity([(t0 + i * 60, 1, 0, 0, 160, 0, 0, 0) for i in minutes])
    captured = []
    monkeypatch.setattr(I, "activity_intensity", lambda days: captured.extend(days))
    result = db.insights(date)
    day = next(d for d in captured if d["date"] == date)
    assert day["trimp"] == len(minutes) * I.edwards_trimp(160, I.hr_max(None))
    assert result["sampling"]["load_method"] == "observed_minutes_only"
    assert result["sampling"]["expected_hr_interval_seconds"] is None
    db.close()
