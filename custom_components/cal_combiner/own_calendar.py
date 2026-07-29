"""The calendar every Cal Combiner merged calendar automatically owns.

Rather than forcing the user to first set up a separate Local Calendar
integration to use as a write target, each merged calendar gets its own small
built-in calendar (backed by Home Assistant's storage helper) that new events
are written to by default. It behaves like any other `calendar.*` entity, so
it also shows up as a normal source that can be merged, filtered on, edited,
etc.
"""
from __future__ import annotations

from datetime import date, datetime
import logging
from typing import Any
import uuid

from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_ICON, CONF_NAME, CONF_PICTURE, DEFAULT_OWN_ICON, DOMAIN

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1


def _parse(value: str):
    return dt_util.parse_datetime(value) or dt_util.parse_date(value)


def _serialize(value: date | datetime) -> str:
    return value.isoformat()


class OwnCalendarStore:
    """Persists this merged calendar's own events as plain JSON."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_own_{entry_id}")
        self.events: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self.events = (data or {}).get("events", [])

    async def _async_save(self) -> None:
        await self._store.async_save({"events": self.events})

    def _to_calendar_event(self, item: dict[str, Any]) -> CalendarEvent:
        return CalendarEvent(
            start=_parse(item["start"]),
            end=_parse(item["end"]),
            summary=item.get("summary", ""),
            description=item.get("description"),
            location=item.get("location"),
            uid=item["uid"],
        )

    def events_in_range(self, start, end) -> list[CalendarEvent]:
        result = []
        for item in self.events:
            ev_start = _parse(item["start"])
            ev_end = _parse(item["end"])
            if str(ev_end) >= str(start) and str(ev_start) <= str(end):
                result.append(self._to_calendar_event(item))
        result.sort(key=lambda e: str(e.start))
        return result

    def upcoming(self, now) -> CalendarEvent | None:
        upcoming = [self._to_calendar_event(i) for i in self.events if str(i["end"]) >= str(now)]
        upcoming.sort(key=lambda e: str(e.start))
        return upcoming[0] if upcoming else None

    async def async_create_event(self, **kwargs: Any) -> CalendarEvent:
        item = {
            "uid": kwargs.get("uid") or str(uuid.uuid4()),
            "summary": kwargs.get("summary", ""),
            "description": kwargs.get("description"),
            "location": kwargs.get("location"),
            "start": _serialize(kwargs["dtstart"]),
            "end": _serialize(kwargs["dtend"]),
        }
        self.events.append(item)
        await self._async_save()
        return self._to_calendar_event(item)

    async def async_update_event(self, uid: str, event: dict[str, Any]) -> None:
        for item in self.events:
            if item["uid"] == uid:
                item["summary"] = event.get("summary", item.get("summary", ""))
                item["description"] = event.get("description", item.get("description"))
                item["location"] = event.get("location", item.get("location"))
                if "dtstart" in event:
                    item["start"] = _serialize(event["dtstart"])
                if "dtend" in event:
                    item["end"] = _serialize(event["dtend"])
                await self._async_save()
                return
        raise KeyError(uid)

    async def async_delete_event(self, uid: str) -> None:
        before = len(self.events)
        self.events = [i for i in self.events if i["uid"] != uid]
        if len(self.events) == before:
            raise KeyError(uid)
        await self._async_save()


async def async_setup_own_entity(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> "OwnCalendarEntity":
    """Create, load and register the own calendar entity for a merge entry."""
    entity = OwnCalendarEntity(hass, entry)
    await entity.store.async_load()
    async_add_entities([entity])
    return entity


class OwnCalendarEntity(CalendarEntity):
    """The calendar this merged calendar automatically owns and writes to."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self.store = OwnCalendarStore(hass, entry.entry_id)
        self._attr_unique_id = f"{entry.entry_id}_own"
        self._attr_name = f"{entry.data.get(CONF_NAME, 'Kalender')} (egen)"

    @property
    def icon(self) -> str:
        return self._entry.data.get(CONF_ICON) or DEFAULT_OWN_ICON

    @property
    def entity_picture(self) -> str | None:
        return self._entry.data.get(CONF_PICTURE) or None

    @property
    def event(self) -> CalendarEvent | None:
        return self.store.upcoming(dt_util.now())

    async def async_get_events(self, hass, start_date, end_date) -> list[CalendarEvent]:
        return self.store.events_in_range(start_date, end_date)

    async def async_create_event(self, **kwargs: Any) -> None:
        await self.store.async_create_event(**kwargs)
        self.async_write_ha_state()

    async def async_update_event(
        self, uid: str, event: dict[str, Any], recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        await self.store.async_update_event(uid, event)
        self.async_write_ha_state()

    async def async_delete_event(
        self, uid: str, recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        await self.store.async_delete_event(uid)
        self.async_write_ha_state()
