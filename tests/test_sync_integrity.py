"""Minute-resolution BLE requests must safely replay late spot readings."""
import datetime as dt
from unittest.mock import AsyncMock

import pytest

from miband6 import protocol as P
from miband6.config import Store
from miband6.healthdb import HealthDB
from miband6.web.server import BandService


def test_spot_cursor_rounds_to_next_wire_minute(tmp_path):
    db = HealthDB(tmp_path / "health.sqlite3")
    ts = 1_700_000_040  # minute boundary
    start = dt.datetime.fromtimestamp(ts).astimezone()
    payload = (ts + 25).to_bytes(4, "little") + bytes([38])
    assert BandService._store_health(db, "stress_manual", start, payload) == ts + 60
    db.close()


async def test_replay_recovers_late_same_minute_spot_and_is_idempotent(tmp_path):
    service = BandService(Store(tmp_path / "config.json"), demo=True)
    db = HealthDB(tmp_path / "health.sqlite3")
    ts = 1_700_000_040
    db.add_stress([(ts + 25, 38)], auto=False)
    db.set_last("stress_manual", ts + 60)
    calls = []

    async def fetch(kind, since):
        calls.append(since.timestamp())
        if since.timestamp() >= ts + 60:
            return None, b""
        payload = b"".join(t.to_bytes(4, "little") + bytes([v])
                           for t, v in [(ts + 25, 38), (ts + 45, 41)])
        return dt.datetime.fromtimestamp(ts).astimezone(), payload

    band = type("Band", (), {"fetch_data": staticmethod(fetch)})()
    await service._sync_one(band, db, "stress_manual", P.FETCH_STRESS_MANUAL)
    await service._sync_one(band, db, "stress_manual", P.FETCH_STRESS_MANUAL)
    assert calls[0] <= ts
    assert db.db.execute("SELECT COUNT(*) FROM stress").fetchone()[0] == 2
    assert db.last("stress_manual") == ts + 60
    db.close()


async def test_failed_fetch_does_not_advance_checkpoint(tmp_path):
    service = BandService(Store(tmp_path / "config.json"), demo=True)
    db = HealthDB(tmp_path / "health.sqlite3")
    db.set_last("activity", 1_700_000_000)
    band = type("Band", (), {"fetch_data": AsyncMock(side_effect=TimeoutError)})()
    with pytest.raises(TimeoutError):
        await service._sync_one(band, db, "activity", P.FETCH_ACTIVITY)
    assert db.last("activity") == 1_700_000_000
    db.close()


def test_state_distinguishes_cached_settings_from_readback(tmp_path):
    service = BandService(Store(tmp_path / "config.json"), demo=True)
    provenance = service.state()["settings_provenance"]
    assert provenance["readback_supported"] is False
    assert provenance["device_readback"] == ["alarms"]
    assert provenance["source"] == "local_requested"


async def test_partial_sync_keeps_last_success_and_invalidates_insights(tmp_path):
    service = BandService(Store(tmp_path / "config.json"), demo=True)
    service.store.data["last_device"] = "test-band"
    service.band = type("Band", (), {"is_connected": True, "authenticated": True})()
    db = service.health_db()
    db.set_last("last_sync", 123)
    service._insight_cache = {"key": "stale"}
    service._sync_one = AsyncMock(side_effect=[TimeoutError(), None, None, None, None, None])
    service._backfill_one = AsyncMock()
    await service._sync_health(service.band)
    assert service.health_status["state"] == "error"
    assert service.health_status["errors"]
    assert db.last("last_sync") == 123
    assert not service._insight_cache
    db.close()


async def test_backfill_page_limit_resumes_without_restarting(tmp_path):
    service = BandService(Store(tmp_path / "config.json"), demo=True)
    db = HealthDB(tmp_path / "health.sqlite3")
    ts = 1_700_000_040
    db.set_last("stress_manual_backfill_cursor", ts)
    db.set_last("stress_manual_backfill_stop", ts + 300 * 60)
    calls = []

    async def fetch(kind, since):
        t = int(since.timestamp())
        calls.append(t)
        return since, t.to_bytes(4, "little") + bytes([38])

    band = type("Band", (), {"fetch_data": staticmethod(fetch)})()
    with pytest.raises(RuntimeError, match="page limit"):
        await service._backfill_one(band, db, "stress_manual", P.FETCH_STRESS_MANUAL)
    assert db.last("stress_manual_backfill") is None
    assert db.last("stress_manual_backfill_cursor") == ts + 200 * 60
    await service._backfill_one(band, db, "stress_manual", P.FETCH_STRESS_MANUAL)
    assert calls[200] == ts + 200 * 60
    assert db.last("stress_manual_backfill")
    assert db.db.execute("SELECT COUNT(*) FROM stress").fetchone()[0] == 300
    db.close()
