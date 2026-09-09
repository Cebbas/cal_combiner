"""Tests for create/update/delete routing: own store vs. external source.

Mirrors the CalDAV server's PUT/DELETE handlers and Home Assistant's own
calendar dashboard, both of which go through create_event/update_event/
delete_event in calendar.py.
"""
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.calendar import CalendarEntityFeature
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.cal_combiner.calendar import (
    OWN_SOURCE_MARKER,
    _resolve_uid,
    create_event,
    delete_event,
    update_event,
)


@pytest.fixture(autouse=True)
def _stub_activity_log():
    """Routing is under test here, not the activity log's own Store writes."""
    with patch("custom_components.cal_combiner.calendar.async_log", new=AsyncMock()):
        yield


def _entry(entry_id="entry1", name="Familjekalender"):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"name": name}
    return entry


def _hass_with_source(entity_id: str, *, supports_update=True, supports_delete=True):
    """A hass double whose calendar component resolves `entity_id` to a mock entity."""
    source = MagicMock()
    features = 0
    if supports_update:
        features |= CalendarEntityFeature.UPDATE_EVENT
    if supports_delete:
        features |= CalendarEntityFeature.DELETE_EVENT
    source.supported_features = features
    source.async_update_event = AsyncMock()
    source.async_delete_event = AsyncMock()

    component = MagicMock()
    component.get_entity = MagicMock(return_value=source)

    hass = MagicMock()
    hass.data = {"calendar": component}
    return hass, source


# ---- create_event: always goes to the own store ----


async def test_create_event_writes_to_own_store():
    store = MagicMock()
    store.async_create_event = AsyncMock(return_value=MagicMock(summary="Möte"))
    hass = MagicMock()

    await create_event(hass, _entry(), store, summary="Möte")
    store.async_create_event.assert_awaited_once_with(summary="Möte")


# ---- update_event routing ----


async def test_update_event_routes_own_marker_to_store():
    store = MagicMock()
    store.async_update_event = AsyncMock()
    hass = MagicMock()
    hass.bus = MagicMock()

    uid = f"{OWN_SOURCE_MARKER}::local-uid"
    await update_event(hass, _entry(), store, uid, {"summary": "Ny titel"})

    store.async_update_event.assert_awaited_once_with("local-uid", {"summary": "Ny titel"}, recurrence_id=None)


async def test_update_event_routes_external_marker_to_source_entity():
    hass, source = _hass_with_source("calendar.school")
    store = MagicMock()

    uid = "calendar.school::orig-uid"
    await update_event(hass, _entry(), store, uid, {"summary": "Ny titel"})

    source.async_update_event.assert_awaited_once_with(
        "orig-uid", {"summary": "Ny titel"}, recurrence_id=None, recurrence_range=None
    )


async def test_update_event_raises_if_source_entity_missing():
    hass = MagicMock()
    component = MagicMock()
    component.get_entity = MagicMock(return_value=None)
    hass.data = {"calendar": component}
    store = MagicMock()

    with pytest.raises(HomeAssistantError):
        await update_event(hass, _entry(), store, "calendar.school::orig-uid", {"summary": "X"})


async def test_update_event_raises_if_source_lacks_update_support():
    hass, _source = _hass_with_source("calendar.school", supports_update=False)
    store = MagicMock()

    with pytest.raises(HomeAssistantError):
        await update_event(hass, _entry(), store, "calendar.school::orig-uid", {"summary": "X"})


# ---- delete_event routing ----


async def test_delete_event_routes_own_marker_to_store():
    store = MagicMock()
    store.async_delete_event = AsyncMock()
    hass = MagicMock()

    uid = f"{OWN_SOURCE_MARKER}::local-uid"
    await delete_event(hass, _entry(), store, uid)

    store.async_delete_event.assert_awaited_once_with("local-uid", recurrence_id=None)


async def test_delete_event_routes_external_marker_to_source_entity():
    hass, source = _hass_with_source("calendar.school")
    store = MagicMock()

    await delete_event(hass, _entry(), store, "calendar.school::orig-uid")

    source.async_delete_event.assert_awaited_once_with("orig-uid", recurrence_id=None, recurrence_range=None)


async def test_delete_event_raises_if_source_lacks_delete_support():
    hass, _source = _hass_with_source("calendar.school", supports_delete=False)
    store = MagicMock()

    with pytest.raises(HomeAssistantError):
        await delete_event(hass, _entry(), store, "calendar.school::orig-uid")


# ---- malformed uid ----


def test_resolve_uid_without_separator_raises():
    with pytest.raises(HomeAssistantError):
        _resolve_uid("not-a-merged-uid", action="redigera")
