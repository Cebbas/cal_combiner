"""Tests for iCalendar (.ics) serialization used by the CalDAV server."""
from icalendar import Calendar

from homeassistant.components.calendar import CalendarEvent
from homeassistant.util import dt as dt_util

from custom_components.cal_combiner.caldav import _external_event_to_ics, _own_item_to_ics


def _dt(iso: str):
    return dt_util.parse_datetime(iso)


def test_own_item_to_ics_simple_event_roundtrips():
    item = {
        "uid": "abc-123",
        "summary": "Tandläkare",
        "description": "Ta med försäkringskort",
        "location": "Tandvården",
        "start": "2026-03-10T09:00:00+00:00",
        "end": "2026-03-10T10:00:00+00:00",
    }
    ics_text = _own_item_to_ics(item)
    parsed = Calendar.from_ical(ics_text)
    events = list(parsed.walk("VEVENT"))
    assert len(events) == 1
    ev = events[0]
    assert str(ev["uid"]) == "abc-123"
    assert str(ev["summary"]) == "Tandläkare"
    assert str(ev["description"]) == "Ta med försäkringskort"
    assert str(ev["location"]) == "Tandvården"


def test_own_item_to_ics_without_optional_fields_omits_them():
    item = {
        "uid": "abc-123",
        "summary": "Möte",
        "description": None,
        "location": None,
        "start": "2026-03-10T09:00:00+00:00",
        "end": "2026-03-10T10:00:00+00:00",
    }
    ics_text = _own_item_to_ics(item)
    parsed = Calendar.from_ical(ics_text)
    ev = list(parsed.walk("VEVENT"))[0]
    assert ev.get("description") is None
    assert ev.get("location") is None


def test_own_item_to_ics_recurring_includes_rrule_and_exdate():
    item = {
        "uid": "series-1",
        "summary": "Fotbollsträning",
        "description": None,
        "location": None,
        "start": "2026-03-02T18:00:00+00:00",
        "end": "2026-03-02T19:00:00+00:00",
        "rrule": "FREQ=WEEKLY;COUNT=4",
        "exdates": ["2026-03-09T18:00:00+00:00"],
        "overrides": {},
    }
    ics_text = _own_item_to_ics(item)
    parsed = Calendar.from_ical(ics_text)
    events = list(parsed.walk("VEVENT"))
    assert len(events) == 1
    master = events[0]
    assert str(master["rrule"].to_ical().decode()) == "FREQ=WEEKLY;COUNT=4"
    exdates = master.get("exdate")
    assert exdates is not None


def test_own_item_to_ics_override_becomes_second_vevent_with_recurrence_id():
    item = {
        "uid": "series-1",
        "summary": "Fotbollsträning",
        "description": None,
        "location": None,
        "start": "2026-03-02T18:00:00+00:00",
        "end": "2026-03-02T19:00:00+00:00",
        "rrule": "FREQ=WEEKLY;COUNT=3",
        "exdates": [],
        "overrides": {
            "2026-03-09T18:00:00+00:00": {"summary": "Cupmatch"},
        },
    }
    ics_text = _own_item_to_ics(item)
    parsed = Calendar.from_ical(ics_text)
    events = list(parsed.walk("VEVENT"))
    assert len(events) == 2

    master = next(e for e in events if e.get("recurrence-id") is None)
    override = next(e for e in events if e.get("recurrence-id") is not None)

    assert str(master["uid"]) == "series-1"
    assert str(master["summary"]) == "Fotbollsträning"
    assert str(override["uid"]) == "series-1"
    assert str(override["summary"]) == "Cupmatch"


def test_external_event_to_ics_contains_core_fields():
    event = CalendarEvent(
        start=_dt("2026-03-10T09:00:00+00:00"),
        end=_dt("2026-03-10T10:00:00+00:00"),
        summary="Skolavslutning",
        description="Ta med blommor",
        location="Skolan",
        uid="calendar.school::orig-uid",
    )
    ics_text = _external_event_to_ics(event)
    parsed = Calendar.from_ical(ics_text)
    events = list(parsed.walk("VEVENT"))
    assert len(events) == 1
    ev = events[0]
    assert str(ev["uid"]) == "calendar.school::orig-uid"
    assert str(ev["summary"]) == "Skolavslutning"
    assert str(ev["location"]) == "Skolan"


def test_external_event_to_ics_without_summary_uses_empty_string():
    event = CalendarEvent(
        start=_dt("2026-03-10T09:00:00+00:00"),
        end=_dt("2026-03-10T10:00:00+00:00"),
        summary="",
        description=None,
        location=None,
        uid="calendar.school::orig-uid",
    )
    ics_text = _external_event_to_ics(event)
    parsed = Calendar.from_ical(ics_text)
    ev = list(parsed.walk("VEVENT"))[0]
    assert str(ev["summary"]) == ""
