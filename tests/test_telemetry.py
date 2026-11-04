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
    # Three out of every four minutes are observed, but a five-minute window never exists.
    sparse = {t0 + i * 60: (t0 + i * 60, 9, 0, 0, 60, 0, 0, 0) for i in range(60) if i % 4}
    assert HealthDB._night(sess, sparse, "2026-01-10")["hr_low_at"] is None


@pytest.mark.parametrize(("valid_minutes", "eligible"), [(41, False), (42, True), (60, True)])
def test_recovery_minimum_requires_seventy_percent_of_asleep_minutes(valid_minutes, eligible):
    t0, _ = H.day_bounds("2026-01-10")
    end = t0 + 65 * 60
    sess = {"start": t0, "end": end, "minutes": 60, "deep": 0, "rem": 0, "awake": 5,
            "stages": [[t0, t0 + 60 * 60, "light"], [t0 + 60 * 60, end, "awake"]]}
    rows = {t0 + i * 60: (t0 + i * 60, 9, 0, 0, 60 if i < valid_minutes or i >= 60 else 255, 0, 0, 0)
            for i in range(65)}
    night = HealthDB._night(sess, rows, "2026-01-10")
    assert night["hr"] == 60
    if eligible:
        assert night["hr_low_at"] == pytest.approx(2 / 65)
    else:
        assert night["hr_low_at"] is None


@pytest.mark.parametrize(("minutes", "weights"), [
    ([0, 1, 2], [1, 1, 1]),        # đo mỗi phút: mỗi số đo một phút
    ([0, 5, 10], [5, 5, 1]),       # đo mỗi 5 phút: mỗi số đo đại diện tới số đo kế tiếp; số đo cuối một phút
    ([0, 1, 40], [1, 10, 1]),      # khoảng trống dài: giữ tối đa 10 phút (HR_HOLD), không lấp cả 39 phút
])
def test_training_load_is_time_weighted_and_capped(tmp_path, monkeypatch, minutes, weights):
    from miband6 import insights as I
    db = HealthDB(tmp_path / "health.db")
    date = "2026-01-10"
    t0, _ = H.day_bounds(date)
    db.add_activity([(t0 + i * 60, 1, 0, 0, 160, 0, 0, 0) for i in minutes])
    captured = []
    monkeypatch.setattr(I, "activity_intensity", lambda days: captured.extend(days))
    result = db.insights(date)
    day = next(d for d in captured if d["date"] == date)
    assert day["trimp"] == sum(weights) * I.edwards_trimp(160, I.hr_max(None))
    assert day["hr_minutes"] == sum(weights)
    assert result["sampling"]["load_method"] == "time_weighted"
    assert result["sampling"]["hr_hold_seconds"] == I.HR_HOLD == 600

    captured.clear()
    db.insights(date, profile={"max_hr_override": 175})
    day = next(d for d in captured if d["date"] == date)
    assert day["trimp"] == sum(weights) * 5  # 160 bpm now exceeds 90% of maximum
    db.close()


def test_training_load_does_not_hold_across_off_wrist_minutes(tmp_path, monkeypatch):
    """Tháo vòng ngay sau một số đo: tải không kéo dài qua lúc không đeo; phút không đeo không tính là đeo."""
    from miband6 import insights as I
    db = HealthDB(tmp_path / "health.db")
    date = "2026-01-10"
    t0, _ = H.day_bounds(date)
    rows = [(t0, 1, 0, 0, 160, 0, 0, 0)] + [(t0 + i * 60, H.KIND_NOT_WORN, 0, 0, 255, 0, 0, 0) for i in range(2, 9)]
    rows.append((t0 + 9 * 60, 1, 0, 0, 160, 0, 0, 0))
    db.add_activity(rows)
    captured = []
    monkeypatch.setattr(I, "activity_intensity", lambda days: captured.extend(days))
    db.insights(date)
    day = next(d for d in captured if d["date"] == date)
    assert day["hr_minutes"] == 2 + 1          # 2 phút trước khi tháo (phút 0, 1) + số đo cuối
    assert day["wear"] == 2                    # phút 0 và 9; 7 phút "không đeo" bị loại, phút 1 không có bản ghi
    db.close()


def test_daily_steps_counts_worn_minutes_not_records(tmp_path):
    db = HealthDB(tmp_path / "health.db")
    t0, _ = H.day_bounds("2026-01-10")
    off = [(t0 + i * 60, H.KIND_NOT_WORN, 0, 0, 255, 0, 0, 0) for i in range(1000)]
    on = [(t0 + i * 60, 1, 10, 5, 255, 0, 0, 0) for i in range(1000, 1440)]
    db.add_activity(off + on)
    (row,) = db.daily_steps()
    assert row["minutes"] == 1440 and row["worn"] == 440 and row["steps"] == 2200
    db.close()


def test_unworn_days_do_not_enter_load_baseline():
    from miband6 import insights as I
    assert I._load_day({"wear": 900, "hr_coverage": 0.95})
    assert not I._load_day({"wear": 300, "hr_coverage": 1.0})      # tháo vòng gần cả ngày
    assert not I._load_day({"wear": 900, "hr_coverage": 0.3})      # đo nhịp tim mỗi 30 phút / tắt đo: tải bị đếm thiếu
