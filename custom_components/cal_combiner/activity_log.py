"""Small rolling activity log per config entry, shown in the sidebar panel.

Kept deliberately stateless (load-append-save on every call) rather than a
long-lived cached object in hass.data: log writes are rare (user edits,
event CRUD, source failure transitions - not a hot path), so the simplicity
of not having to hook into each entry's setup/unload lifecycle is worth more
than the small amount of extra I/O.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

STORAGE_VERSION = 1
MAX_ENTRIES = 50


def _store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}_activity_log_{entry_id}")


async def async_log(hass: HomeAssistant, entry_id: str, message: str) -> None:
    store = _store(hass, entry_id)
    data = await store.async_load() or {}
    entries = data.get("entries", [])
    entries.insert(0, {"time": dt_util.now().isoformat(), "message": message})
    del entries[MAX_ENTRIES:]
    await store.async_save({"entries": entries})


async def async_get_entries(hass: HomeAssistant, entry_id: str) -> list[dict]:
    data = await _store(hass, entry_id).async_load() or {}
    return data.get("entries", [])


async def async_clear(hass: HomeAssistant, entry_id: str) -> None:
    await _store(hass, entry_id).async_remove()
