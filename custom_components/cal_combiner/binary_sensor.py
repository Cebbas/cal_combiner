"""Binary sensor platform for Cal Combiner activity sensors."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    CONF_CREATE_BINARY,
    CONF_ENTRY_TYPE,
    CONF_ICON,
    CONF_NAME,
    CONF_PICTURE,
    CONF_TRIGGER_MODE,
    DEFAULT_ACTIVITY_ICON,
    ENTRY_TYPE_ACTIVITY,
    TRIGGER_MODE_TODAY,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ACTIVITY:
        return
    if not entry.data.get(CONF_CREATE_BINARY, True):
        return

    coordinator = await async_get_or_create_coordinator(hass, entry)
    async_add_entities([ActivityBinarySensor(coordinator, entry)])


class ActivityBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """On when at least one matching event is happening right now."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ActivitySensorCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_active"
        self._attr_name = entry.data.get(CONF_NAME, "Aktivitet")

    @property
    def icon(self) -> str:
        return self._entry.data.get(CONF_ICON) or DEFAULT_ACTIVITY_ICON

    @property
    def entity_picture(self) -> str | None:
        return self._entry.data.get(CONF_PICTURE) or None

    @property
    def is_on(self) -> bool:
        now = dt_util.now()
        events = (self.coordinator.data or {}).get("events", [])
        if self._entry.data.get(CONF_TRIGGER_MODE) == TRIGGER_MODE_TODAY:
            return any(event_is_today(e, now) for e in events)
        return any(event_is_active(e, now) for e in events)

    @property
    def extra_state_attributes(self) -> dict:
        now = dt_util.now()
        events = (self.coordinator.data or {}).get("events", [])
        active = [e for e in events if event_is_active(e, now)]
        upcoming = sorted([e for e in events if event_is_upcoming(e, now)], key=lambda e: str(e.start))

        attrs: dict = {}
        if active:
            attrs["current_event"] = active[0].summary
        if upcoming:
            attrs["next_event"] = upcoming[0].summary
            attrs["next_start"] = (
                upcoming[0].start.isoformat()
                if hasattr(upcoming[0].start, "isoformat")
                else str(upcoming[0].start)
            )
        failed = (self.coordinator.data or {}).get("failed") or []
        if failed:
            attrs["failed_sources"] = failed
        return attrs
