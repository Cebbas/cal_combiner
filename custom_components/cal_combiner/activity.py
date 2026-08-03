"""Shared polling logic for activity sensors (binary_sensor + sensor).

Reuses the exact same filter matching (`fetch_merged_events`) as the merged
calendar entities, just applied uniformly across a set of source calendars
instead of per-source.
"""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .activity_log import async_log
from .calendar import fetch_merged_events
from .const import CONF_FILTER, CONF_SOURCES, DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=5)


def event_is_active(event, now) -> bool:
    return str(event.start) <= str(now) <= str(event.end)


def event_is_upcoming(event, now) -> bool:
    return str(event.start) > str(now)


def event_is_today(event, now) -> bool:
    return str(event.start)[:10] == str(now.date())


class ActivitySensorCoordinator(DataUpdateCoordinator):
    """Polls the configured sources and applies the shared filter rule."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=f"cal_combiner_activity_{entry.entry_id}", update_interval=SCAN_INTERVAL
        )
        self.entry = entry
        self._last_failed: set[str] = set()

    async def _async_update_data(self):
        sources: list[str] = self.entry.data.get(CONF_SOURCES, [])
        rule = self.entry.data.get(CONF_FILTER)
        filters = {entity_id: rule for entity_id in sources} if rule else {}

        now = dt_util.now()
        events, failed = await fetch_merged_events(
            self.hass, sources, now - timedelta(hours=1), now + timedelta(days=30), filters
        )

        failed_set = set(failed)
        if failed_set and failed_set != self._last_failed:
            await async_log(self.hass, self.entry.entry_id, "Källa svarar inte: " + ", ".join(failed))
        elif not failed_set and self._last_failed:
            await async_log(self.hass, self.entry.entry_id, "Alla källor svarar igen")
        self._last_failed = failed_set

        return {"events": events, "failed": failed}


async def async_get_or_create_coordinator(
    hass: HomeAssistant, entry: ConfigEntry
) -> ActivitySensorCoordinator:
    """One coordinator per entry, shared between the binary_sensor and sensor platforms."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    key = f"{entry.entry_id}_activity_coordinator"
    coordinator = domain_data.get(key)
    if coordinator is None:
        coordinator = ActivitySensorCoordinator(hass, entry)
        await coordinator.async_config_entry_first_refresh()
        domain_data[key] = coordinator
    return coordinator
