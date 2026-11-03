"""Conservative quality metadata for processed Mi Band 6 readings.

These engineering gates are not diagnostic ranges or a validated artifact detector.
Raw readings stay in SQLite. Suspicious but possible values remain visible; no
smoothing, interpolation or RR/HRV reconstruction is applied to minute averages.
"""
from __future__ import annotations

import math
import statistics


SOURCES = {"hr": "band_processed_ppg", "spo2": "band_spot_oximetry", "stress": "band_proprietary"}


def assess(metric: str, value: float, *, previous: tuple[int, float] | None = None,
           timestamp: int | None = None) -> dict:
    """Return reproducible flags without changing the raw value.

    Abrupt changes within two minutes request a repeat/fit check, never establish
    an artifact. A low oxygen reading alone is never discarded as noise.
    """
    if metric not in SOURCES:
        raise ValueError(f"Unsupported metric: {metric}")
    flags = []
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        status, flags = "invalid", ["non_finite"]
    elif value == 255 or (metric != "stress" and value == 0):
        status, flags = "missing", ["not_measured"]
    elif not ((30 <= value <= 220) if metric == "hr" else (1 <= value <= 100) if metric == "spo2" else (0 <= value <= 100)):
        status, flags = "invalid", ["outside_supported_range"]
    else:
        status = "valid"
        if previous is not None and timestamp is not None and 0 < timestamp - previous[0] <= 120:
            delta = abs(value - previous[1])
            if (metric == "hr" and delta > 60) or (metric == "spo2" and delta > 8):
                status, flags = "suspect", ["abrupt_change"]
    return {"value": value, "status": status, "flags": flags, "usable": status in ("valid", "suspect")}


def sampling(timestamps: list[int], start: int, end: int, *, expected_interval_seconds: int | None = None) -> dict:
    """Coverage counts occupied time slots, not interpolated readings.

    Expected cadence must be supplied, not inferred from sparse data. Observed
    median spacing is descriptive and does not prove the device's configuration.
    """
    if expected_interval_seconds is not None and expected_interval_seconds <= 0:
        raise ValueError("Expected interval must be positive")
    points = sorted({t for t in timestamps if start <= t < end})
    gaps = [b - a for a, b in zip(points, points[1:])]
    expected = math.ceil(max(0, end - start) / expected_interval_seconds) if expected_interval_seconds else None
    occupied = len({(t - start) // expected_interval_seconds for t in points}) if expected_interval_seconds else None
    return {"samples": len(points), "start": start, "end": end,
            "expected_interval_seconds": expected_interval_seconds,
            "observed_median_interval_seconds": statistics.median(gaps) if gaps else None,
            "max_gap_seconds": max(gaps, default=None),
            "missing_slots": max(0, expected - occupied) if expected is not None else None,
            "coverage_ratio": occupied / expected if expected else None,
            "latest_timestamp": points[-1] if points else None}


def series_quality(metric: str, rows: list[tuple], start: int, end: int,
                   expected_interval_seconds: int | None = None) -> dict:
    """Rows begin with timestamp, value; preserve independent manual/auto readings."""
    counts = dict.fromkeys(("valid", "suspect", "invalid", "missing"), 0)
    flagged, usable, previous = [], [], None
    for row in rows:
        ts, value = row[:2]
        result = assess(metric, value, previous=previous, timestamp=ts)
        counts[result["status"]] += 1
        if result["flags"] and result["status"] != "missing":
            flagged.append({"ts": ts, **result})
        if result["usable"]:
            usable.append(ts)
            previous = (ts, value)
    return {"source": SOURCES[metric], "counts": counts, "flagged": flagged,
            "sampling": sampling(usable, start, end, expected_interval_seconds=expected_interval_seconds),
            "raw_rr_available": False if metric == "hr" else None,
            "filter": "range_validation_only; suspicious_values_retained", "version": 1}
