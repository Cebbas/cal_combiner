"""iOS/macOS Calendar compatibility details of the CalDAV server that the
`caldav` library interop test doesn't exercise: calendar-multiget, DTSTAMP,
and no synthetic fixed-offset TZIDs on EXDATE/RECURRENCE-ID."""
import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar

from custom_components.cal_combiner.caldav import (
    _own_item_to_ics,
    async_get_settings,
)
from custom_components.cal_combiner.own_calendar import occurrence_key
from homeassistant.util import dt as dt_util

import pytest

from .test_caldav_interop import _setup_entry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

RECURRING_ITEM = {
    "uid": "serie-1",
    "summary": "Träning",
    "start": "2026-08-18T17:00:00+02:00",
    "end": "2026-08-18T18:00:00+02:00",
    "rrule": "FREQ=WEEKLY;COUNT=20",
    "exdates": ["2026-08-25T17:00:00+02:00"],
    "overrides": {"2026-09-01T17:00:00+02:00": {"summary": "Match"}},
}


@pytest.fixture
async def stockholm(hass):
    await hass.config.async_set_time_zone("Europe/Stockholm")


async def test_recurring_item_is_served_in_named_zone_with_vtimezone(hass, stockholm):
    text = _own_item_to_ics(RECURRING_ITEM)
    assert 'TZID="UTC' not in text and "TZID=UTC" not in text
    assert "BEGIN:VTIMEZONE" in text
    assert "DTSTART;TZID=Europe/Stockholm:20260818T170000" in text
    vevents = list(Calendar.from_ical(text).walk("VEVENT"))
    assert len(vevents) == 2
    assert all(v.get("dtstamp") is not None for v in vevents)
    override = next(v for v in vevents if v.get("recurrence-id"))
    assert override.get("recurrence-id").dt == datetime(2026, 9, 1, 15, 0, tzinfo=dt_util.UTC)


async def test_client_recurrence_id_maps_to_canonical_key(hass, stockholm):
    stored = "2026-09-01T17:00:00+02:00"
    assert occurrence_key(datetime(2026, 9, 1, 15, 0, tzinfo=dt_util.UTC)) == stored
    assert occurrence_key(datetime(2026, 9, 1, 17, 0, tzinfo=ZoneInfo("Europe/Stockholm"))) == stored
    # Winter: same wall time, different offset.
    assert occurrence_key(datetime(2026, 11, 3, 16, 0, tzinfo=dt_util.UTC)) == "2026-11-03T17:00:00+01:00"


async def test_calendar_multiget_returns_requested_hrefs_only(hass, aiohttp_client, socket_enabled):
    entry = await _setup_entry(hass)
    store = hass.data["cal_combiner"][entry.entry_id]["own_store"]
    start = dt_util.now().replace(microsecond=0)
    await store.async_put_master(
        "abc", summary="Tandläkare", description=None, location=None,
        start=start, end=start + timedelta(hours=1),
        rrule=None, exdates=[], overrides={},
    )
    await store.async_put_master(
        "other", summary="Annat", description=None, location=None,
        start=start, end=start + timedelta(hours=1), rrule=None, exdates=[], overrides={},
    )
    client = await aiohttp_client(hass.http.app)
    token = (await async_get_settings(hass))["token"]
    col = f"/api/cal_combiner/dav/{entry.entry_id}/"
    body = (
        '<?xml version="1.0"?><c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
        f"<d:href>{col}abc.ics</d:href><d:href>{col}missing.ics</d:href></c:calendar-multiget>"
    )
    resp = await client.request(
        "REPORT", col, data=body,
        headers={"Authorization": "Basic " + base64.b64encode(f"u:{token}".encode()).decode(), "Depth": "1"},
    )
    assert resp.status == 207
    text = await resp.text()
    assert "Tandläkare" in text
    assert "Annat" not in text
    assert "missing.ics</D:href><D:status>HTTP/1.1 404" in text
