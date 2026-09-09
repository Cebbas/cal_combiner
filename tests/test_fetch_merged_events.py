"""Tests for fetch_merged_events: querying sources, applying filter/rename, merging."""
from unittest.mock import AsyncMock, MagicMock

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


async def test_missing_uid_falls_back_to_summary():
    hass = _hass_returning(
        {
            "calendar.a": [
                {"summary": "Ingen uid", "start": "2026-03-20T09:00:00+00:00", "end": "2026-03-20T10:00:00+00:00"}
            ]
        }
    )
    events, _failed = await fetch_merged_events(hass, ["calendar.a"], START, END)
    assert events[0].uid == "calendar.a::Ingen uid"


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
