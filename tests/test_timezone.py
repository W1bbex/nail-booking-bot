import json
import sys
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfoNotFoundError

import pytest

from core import catalog_service, config, slot_service
from core.booking_service import cancel_booking, create_booking
from core.config import settings


FIXED_UTC = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXED_UTC.astimezone(tz) if tz is not None else FIXED_UTC.replace(tzinfo=None)


@pytest.mark.parametrize("zone, expected", [
    ("Europe/Moscow", datetime(2026, 11, 20, 18)),
    ("Asia/Vladivostok", datetime(2026, 11, 21, 1)),
])
@pytest.mark.parametrize("module", [slot_service, catalog_service])
def test_salon_clock_uses_selected_timezone(monkeypatch, module, zone, expected):
    monkeypatch.setattr(settings, "salon", {"timezone": zone})
    monkeypatch.setattr(module, "datetime", FrozenDateTime)
    assert module.get_moscow_now() == expected


@pytest.mark.parametrize("module", [slot_service, catalog_service])
def test_invalid_timezone_never_silently_becomes_moscow(monkeypatch, module):
    monkeypatch.setattr(settings, "salon", {"timezone": "Invalid/Salon"})
    with pytest.raises((ValueError, ZoneInfoNotFoundError)):
        module.get_moscow_now()


def test_startup_rejects_invalid_timezone(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"salon": {"timezone": "Invalid/Salon"}}), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    with pytest.raises(SystemExit):
        config.Settings()


def test_admin_rejects_invalid_timezone_before_mutating_settings(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    original = {"salon": {"timezone": "Europe/Moscow"}}
    path.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(catalog_service, "CONFIG_PATH", path)
    monkeypatch.setattr(settings, "salon", dict(original["salon"]))
    with pytest.raises((ValueError, ZoneInfoNotFoundError)):
        catalog_service.update_salon_settings({"timezone": "Invalid/Salon"})
    assert settings.salon == original["salon"]
    assert json.loads(path.read_text(encoding="utf-8")) == original


@pytest.mark.asyncio
async def test_vladivostok_midnight_slots_and_cancellation_deadline(db_session, monkeypatch):
    monkeypatch.setattr(settings, "salon", {"timezone": "Asia/Vladivostok"})
    monkeypatch.setattr(slot_service, "datetime", FrozenDateTime)
    booking = await create_booking(db_session, 999000101, "Synthetic client", "+70000000000",
                                   1, 2, date(2026, 11, 21), time(10))
    assert await slot_service.get_available_slots(db_session, 1, 2, date(2026, 11, 20)) == []
    # 23:00 UTC is already 09:00 next day in the salon: one hour before the visit.
    monkeypatch.setattr(sys.modules[__name__], "FIXED_UTC",
                        datetime(2026, 11, 20, 23, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="не позднее"):
        await cancel_booking(db_session, booking.id, 999000101)
