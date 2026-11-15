"""Tests for fetch_merged_events: querying sources, applying filter/rename, merging."""
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.calendar import CalendarEvent
from homeassistant.util import dt as dt_util

from custom_components.cal_combiner.calendar import fetch_merged_events

START = dt_util.parse_datetime("2026-03-01T00:00:00+00:00")
END = dt_util.parse_datetime("2026-03-31T00:00:00+00:00")


def _hass_returning(per_source: dict[str, list[dict] | Exception]):
    """A hass double whose calendar.get_events service call returns canned events per source."""
    hass = MagicMock()

    async def _async_call(domain, service, data, blocking=True, return_response=True):
        entity_id = data["entity_id"]
        result = per_source[entity_id]
        if isinstance(result, Exception):
            raise result
        return {entity_id: {"events": result}}

    hass.services.async_call = AsyncMock(side_effect=_async_call)
    # No calendar component -> fetch_merged_events uses the service fallback.
    hass.data = {}
    return hass


async def test_merges_events_from_multiple_sources_sorted_by_start():
    hass = _hass_returning(
        {
            "calendar.a": [
                {"uid": "1", "summary": "Sent", "start": "2026-03-20T09:00:00+00:00", "end": "2026-03-20T10:00:00+00:00"}
            ],
            "calendar.b": [
                {"uid": "2", "summary": "Tidigt", "start": "2026-03-05T09:00:00+00:00", "end": "2026-03-05T10:00:00+00:00"}
            ],
        }
    )
    events, failed = await fetch_merged_events(hass, ["calendar.a", "calendar.b"], START, END)
    assert failed == []
    assert [e.summary for e in events] == ["Tidigt", "Sent"]


async def test_uid_is_prefixed_with_source_entity_id():
    hass = _hass_returning(
        {
            "calendar.a": [
                {"uid": "orig-1", "summary": "X", "start": "2026-03-20T09:00:00+00:00", "end": "2026-03-20T10:00:00+00:00"}
            ]
        }
    )
    events, _failed = await fetch_merged_events(hass, ["calendar.a"], START, END)
    assert events[0].uid == "calendar.a::orig-1"


async def test_missing_uid_falls_back_to_summary_and_start():
    hass = _hass_returning(
        {
            "calendar.a": [
                {"summary": "Ingen uid", "start": "2026-03-20T09:00:00+00:00", "end": "2026-03-20T10:00:00+00:00"}
            ]
        }
    )
    events, _failed = await fetch_merged_events(hass, ["calendar.a"], START, END)
    # Summary alone would give every occurrence of a series the same uid.
    assert events[0].uid == "calendar.a::Ingen uid@2026-03-20 09:00:00+00:00"


async def test_all_day_event_parsed_as_date_not_datetime():
    hass = _hass_returning(
        {"calendar.a": [{"uid": "1", "summary": "Lovdag", "start": "2026-06-01", "end": "2026-06-02"}]}
    )
    events, _failed = await fetch_merged_events(hass, ["calendar.a"], START, END)
    from datetime import date

    assert type(events[0].start) is date


async def test_per_source_filter_excludes_non_matching_events():
    hass = _hass_returning(
        {
            "calendar.a": [
                {"uid": "1", "summary": "Fotboll", "start": "2026-03-20T09:00:00+00:00", "end": "2026-03-20T10:00:00+00:00"},
                {"uid": "2", "summary": "Hockey", "start": "2026-03-21T09:00:00+00:00", "end": "2026-03-21T10:00:00+00:00"},
            ]
        }
    )
    filters = {"calendar.a": {"include": ["fotboll"]}}
    events, _failed = await fetch_merged_events(hass, ["calendar.a"], START, END, filters=filters)
    assert [e.summary for e in events] == ["Fotboll"]


async def test_filter_and_rename_only_apply_to_their_own_source():
    hass = _hass_returning(
        {
            "calendar.a": [
                {"uid": "1", "summary": "Träning // Team A", "start": "2026-03-20T09:00:00+00:00", "end": "2026-03-20T10:00:00+00:00"}
            ],
            "calendar.b": [
                {"uid": "2", "summary": "Träning // Team A", "start": "2026-03-21T09:00:00+00:00", "end": "2026-03-21T10:00:00+00:00"}
            ],
        }
    )
    renames = {"calendar.a": [{"pattern": r" // .*$", "replacement": ""}]}
    events, _failed = await fetch_merged_events(hass, ["calendar.a", "calendar.b"], START, END, renames=renames)
    by_source = {e.uid.split("::")[0]: e.summary for e in events}
    assert by_source["calendar.a"] == "Träning"
    assert by_source["calendar.b"] == "Träning // Team A"


async def test_failing_source_is_reported_but_others_still_merge():
    hass = _hass_returning(
        {
            "calendar.a": [
                {"uid": "1", "summary": "OK", "start": "2026-03-20T09:00:00+00:00", "end": "2026-03-20T10:00:00+00:00"}
            ],
            "calendar.b": ConnectionError("timeout"),
        }
    )
    events, failed = await fetch_merged_events(hass, ["calendar.a", "calendar.b"], START, END)
    assert failed == ["calendar.b"]
    assert [e.summary for e in events] == ["OK"]


# ---- live source entity (the normal path) ----


def _hass_with_entities(per_source: dict[str, list[CalendarEvent] | Exception]):
    """A hass double whose calendar component resolves each source to an entity double.

    Mirrors real Home Assistant: the entity returns full CalendarEvents
    (uid + recurrence_id), and the `calendar.get_events` service - which
    strips both - must not be used at all.
    """
    entities = {}
    for entity_id, result in per_source.items():
        entity = MagicMock()
        if isinstance(result, Exception):
            entity.async_get_events = AsyncMock(side_effect=result)
        else:
            entity.async_get_events = AsyncMock(return_value=result)
        entities[entity_id] = entity

    component = MagicMock()
    component.get_entity = MagicMock(side_effect=entities.get)
    hass = MagicMock()
    hass.data = {"calendar": component}
    hass.services.async_call = AsyncMock(side_effect=AssertionError("service must not be used"))
    return hass


def _occurrence(day: int, recurrence_id: str | None = "20260320T090000Z"):
    return CalendarEvent(
        start=dt_util.parse_datetime(f"2026-03-{day:02d}T09:00:00+00:00"),
        end=dt_util.parse_datetime(f"2026-03-{day:02d}T10:00:00+00:00"),
        summary="Träning",
        uid="series-1",
        recurrence_id=recurrence_id,
    )


async def test_entity_path_keeps_real_uid():
    hass = _hass_with_entities({"calendar.a": [_occurrence(20, recurrence_id=None)]})
    events, failed = await fetch_merged_events(hass, ["calendar.a"], START, END)
    assert failed == []
    assert events[0].uid == "calendar.a::series-1"


async def test_occurrences_of_a_recurring_source_event_get_unique_uids():
    hass = _hass_with_entities(
        {"calendar.a": [_occurrence(13, "20260313T090000Z"), _occurrence(20, "20260320T090000Z")]}
    )
    events, _failed = await fetch_merged_events(hass, ["calendar.a"], START, END)
    uids = [e.uid for e in events]
    assert len(set(uids)) == 2
    assert uids == [
        "calendar.a::series-1::rid::20260313T090000Z",
        "calendar.a::series-1::rid::20260320T090000Z",
    ]


async def test_entity_path_applies_filter_and_rename():
    hass = _hass_with_entities({"calendar.a": [_occurrence(20, recurrence_id=None)]})
    renames = {"calendar.a": [{"pattern": "^Träning$", "replacement": "Fotbollsträning"}]}
    filters = {"calendar.a": {"include": ["träning"]}}
    events, _failed = await fetch_merged_events(hass, ["calendar.a"], START, END, filters, renames)
    assert [e.summary for e in events] == ["Fotbollsträning"]


async def test_entity_failure_is_reported_and_others_still_merge():
    hass = _hass_with_entities(
        {"calendar.a": [_occurrence(20, recurrence_id=None)], "calendar.b": ConnectionError("timeout")}
    )
    events, failed = await fetch_merged_events(hass, ["calendar.a", "calendar.b"], START, END)
    assert failed == ["calendar.b"]
    assert [e.summary for e in events] == ["Träning"]
