"""Tests for OwnCalendarStore: recurrence expansion (RRULE/exdate/override) and CRUD."""
from datetime import date, datetime

from homeassistant.util import dt as dt_util
import pytest

from custom_components.cal_combiner.own_calendar import OwnCalendarStore


def _dt(iso: str) -> datetime:
    return dt_util.parse_datetime(iso)


# ---- expansion of a plain (non-recurring) event ----


async def test_non_recurring_event_in_range_is_returned(hass):
    store = OwnCalendarStore(hass, "entry1")
    await store.async_create_event(
        summary="Tandläkare",
        dtstart=_dt("2026-03-10T09:00:00+00:00"),
        dtend=_dt("2026-03-10T10:00:00+00:00"),
    )
    events = store.events_in_range(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    assert len(events) == 1
    assert events[0].summary == "Tandläkare"


async def test_non_recurring_event_outside_range_is_excluded(hass):
    store = OwnCalendarStore(hass, "entry1")
    await store.async_create_event(
        summary="Tandläkare",
        dtstart=_dt("2026-03-10T09:00:00+00:00"),
        dtend=_dt("2026-03-10T10:00:00+00:00"),
    )
    events = store.events_in_range(_dt("2026-04-01T00:00:00+00:00"), _dt("2026-04-30T00:00:00+00:00"))
    assert events == []


# ---- recurrence expansion ----


async def test_weekly_recurrence_expands_multiple_occurrences(hass):
    store = OwnCalendarStore(hass, "entry1")
    await store.async_create_event(
        summary="Fotbollsträning",
        dtstart=_dt("2026-03-02T18:00:00+00:00"),
        dtend=_dt("2026-03-02T19:00:00+00:00"),
        rrule="FREQ=WEEKLY;COUNT=4",
    )
    events = store.events_in_range(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    assert [str(e.start.date()) for e in events] == ["2026-03-02", "2026-03-09", "2026-03-16", "2026-03-23"]
    assert all(e.summary == "Fotbollsträning" for e in events)


async def test_events_in_range_sorted_by_start(hass):
    store = OwnCalendarStore(hass, "entry1")
    await store.async_create_event(
        summary="Sent", dtstart=_dt("2026-03-20T09:00:00+00:00"), dtend=_dt("2026-03-20T10:00:00+00:00")
    )
    await store.async_create_event(
        summary="Tidigt", dtstart=_dt("2026-03-05T09:00:00+00:00"), dtend=_dt("2026-03-05T10:00:00+00:00")
    )
    events = store.events_in_range(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    assert [e.summary for e in events] == ["Tidigt", "Sent"]


async def test_exdate_removes_one_occurrence(hass):
    store = OwnCalendarStore(hass, "entry1")
    event = await store.async_create_event(
        summary="Fotbollsträning",
        dtstart=_dt("2026-03-02T18:00:00+00:00"),
        dtend=_dt("2026-03-02T19:00:00+00:00"),
        rrule="FREQ=WEEKLY;COUNT=3",
    )
    occ_key = "2026-03-09T18:00:00+00:00"
    occurrence_uid = f"{event.uid}/{occ_key}"
    await store.async_delete_event(occurrence_uid)

    events = store.events_in_range(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    assert [str(e.start.date()) for e in events] == ["2026-03-02", "2026-03-16"]


async def test_override_changes_a_single_occurrence(hass):
    store = OwnCalendarStore(hass, "entry1")
    event = await store.async_create_event(
        summary="Fotbollsträning",
        dtstart=_dt("2026-03-02T18:00:00+00:00"),
        dtend=_dt("2026-03-02T19:00:00+00:00"),
        rrule="FREQ=WEEKLY;COUNT=3",
    )
    occ_key = "2026-03-09T18:00:00+00:00"
    occurrence_uid = f"{event.uid}/{occ_key}"
    await store.async_update_event(occurrence_uid, {"summary": "Inställd -> Cupmatch"})

    events = store.events_in_range(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    by_date = {str(e.start.date()): e.summary for e in events}
    assert by_date["2026-03-02"] == "Fotbollsträning"
    assert by_date["2026-03-09"] == "Inställd -> Cupmatch"
    assert by_date["2026-03-16"] == "Fotbollsträning"


async def test_update_whole_series_changes_every_occurrence(hass):
    store = OwnCalendarStore(hass, "entry1")
    event = await store.async_create_event(
        summary="Fotbollsträning",
        dtstart=_dt("2026-03-02T18:00:00+00:00"),
        dtend=_dt("2026-03-02T19:00:00+00:00"),
        rrule="FREQ=WEEKLY;COUNT=3",
    )
    await store.async_update_event(event.uid, {"summary": "Innebandyträning"})

    events = store.events_in_range(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    assert all(e.summary == "Innebandyträning" for e in events)


async def test_update_can_turn_a_plain_event_into_a_recurring_series(hass):
    store = OwnCalendarStore(hass, "entry1")
    event = await store.async_create_event(
        summary="Fotbollsträning",
        dtstart=_dt("2026-03-02T18:00:00+00:00"),
        dtend=_dt("2026-03-02T19:00:00+00:00"),
    )
    await store.async_update_event(event.uid, {"rrule": "FREQ=WEEKLY;COUNT=3"})

    events = store.events_in_range(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    assert [str(e.start.date()) for e in events] == ["2026-03-02", "2026-03-09", "2026-03-16"]


async def test_update_without_rrule_key_leaves_existing_series_untouched(hass):
    store = OwnCalendarStore(hass, "entry1")
    event = await store.async_create_event(
        summary="Fotbollsträning",
        dtstart=_dt("2026-03-02T18:00:00+00:00"),
        dtend=_dt("2026-03-02T19:00:00+00:00"),
        rrule="FREQ=WEEKLY;COUNT=3",
    )
    # Same as test_update_whole_series_changes_every_occurrence, but this
    # asserts specifically that omitting "rrule" from the update payload
    # (the normal case - most edits don't touch recurrence at all) never
    # silently drops the series' existing rrule.
    await store.async_update_event(event.uid, {"summary": "Innebandyträning"})

    events = store.events_in_range(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    assert len(events) == 3
    assert all(e.summary == "Innebandyträning" for e in events)


async def test_update_with_empty_rrule_clears_recurrence(hass):
    store = OwnCalendarStore(hass, "entry1")
    event = await store.async_create_event(
        summary="Fotbollsträning",
        dtstart=_dt("2026-03-02T18:00:00+00:00"),
        dtend=_dt("2026-03-02T19:00:00+00:00"),
        rrule="FREQ=WEEKLY;COUNT=3",
    )
    await store.async_update_event(event.uid, {"rrule": ""})

    events = store.events_in_range(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    assert [str(e.start.date()) for e in events] == ["2026-03-02"]


async def test_all_day_event_is_date_only(hass):
    store = OwnCalendarStore(hass, "entry1")
    # Direct manipulation to avoid needing the storage layer for this pure-expansion check.
    store.events = [
        {"uid": "u1", "summary": "Lovdag", "start": "2026-06-01", "end": "2026-06-02"}
    ]
    events = store.events_in_range(date(2026, 5, 1), date(2026, 6, 30))
    assert len(events) == 1
    assert events[0].start == date(2026, 6, 1)


# ---- delete ----


async def test_delete_nonexistent_event_raises_keyerror(hass):
    store = OwnCalendarStore(hass, "entry1")
    with pytest.raises(KeyError):
        await store.async_delete_event("does-not-exist")


async def test_delete_whole_series_removes_it_entirely(hass):
    store = OwnCalendarStore(hass, "entry1")
    event = await store.async_create_event(
        summary="Fotbollsträning",
        dtstart=_dt("2026-03-02T18:00:00+00:00"),
        dtend=_dt("2026-03-02T19:00:00+00:00"),
        rrule="FREQ=WEEKLY;COUNT=3",
    )
    await store.async_delete_event(event.uid)
    events = store.events_in_range(_dt("2026-03-01T00:00:00+00:00"), _dt("2026-03-31T00:00:00+00:00"))
    assert events == []


# ---- ctag bumps on every mutation (CalDAV clients rely on this) ----


async def test_ctag_increments_on_mutation(hass):
    store = OwnCalendarStore(hass, "entry1")
    assert store.ctag == 0
    await store.async_create_event(
        summary="X", dtstart=_dt("2026-03-02T18:00:00+00:00"), dtend=_dt("2026-03-02T19:00:00+00:00")
    )
    assert store.ctag == 1
