"""Sensor platform for Cal Combiner activity sensors."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .activity import (
    ActivitySensorCoordinator,
    async_get_or_create_coordinator,
    event_is_active,
    event_is_today,
    event_is_upcoming,
)
from .const import (
    CONF_CREATE_SENSOR,
    CONF_ENTRY_TYPE,
    CONF_ICON,
    CONF_NAME,
    CONF_PICTURE,
    DEFAULT_ACTIVITY_ICON,
    ENTRY_TYPE_ACTIVITY,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ACTIVITY:
        return
    if not entry.data.get(CONF_CREATE_SENSOR, True):
        return

    coordinator = await async_get_or_create_coordinator(hass, entry)
    async_add_entities([ActivitySensor(coordinator, entry)])


class ActivitySensor(CoordinatorEntity, SensorEntity):
    """State = title of the currently active (or next upcoming) matching event."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ActivitySensorCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_next"
        self._attr_name = entry.data.get(CONF_NAME, "Aktivitet")

    @property
    def icon(self) -> str:
        return self._entry.data.get(CONF_ICON) or DEFAULT_ACTIVITY_ICON

    @property
    def entity_picture(self) -> str | None:
        return self._entry.data.get(CONF_PICTURE) or None

    @property
    def native_value(self) -> str:
        now = dt_util.now()
        events = (self.coordinator.data or {}).get("events", [])
        active = [e for e in events if event_is_active(e, now)]
        if active:
            return active[0].summary

        upcoming = sorted([e for e in events if event_is_upcoming(e, now)], key=lambda e: str(e.start))
        return upcoming[0].summary if upcoming else "Inga kommande event"

    @property
    def extra_state_attributes(self) -> dict:
        now = dt_util.now()
        events = (self.coordinator.data or {}).get("events", [])
        upcoming = sorted([e for e in events if event_is_upcoming(e, now)], key=lambda e: str(e.start))
        today_count = sum(1 for e in events if event_is_today(e, now))

        attrs: dict = {"matches_today": today_count}
        if upcoming:
            next_event = upcoming[0]
            attrs["next_start"] = (
                next_event.start.isoformat() if hasattr(next_event.start, "isoformat") else str(next_event.start)
            )
            attrs["next_end"] = (
                next_event.end.isoformat() if hasattr(next_event.end, "isoformat") else str(next_event.end)
            )
            if next_event.location:
                attrs["location"] = next_event.location
        failed = (self.coordinator.data or {}).get("failed") or []
        if failed:
            attrs["failed_sources"] = failed
        return attrs
