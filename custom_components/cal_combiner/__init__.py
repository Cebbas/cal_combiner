"""The Cal Combiner integration."""
from __future__ import annotations

import logging

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    CONF_ENTRY_TYPE,
    CONF_NAME,
    CONF_TOKEN,
    DOMAIN,
    ENTRY_TYPE_MERGE,
    PLATFORMS_ACTIVITY,
    PLATFORMS_MERGE,
)
from .http import async_setup_feed_view
from .panel import async_register_panel
from .ws_api import async_register_ws_api

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async_register_ws_api(hass)
    await async_register_panel(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"entry": entry}

    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MERGE)

    if entry_type == ENTRY_TYPE_MERGE:
        await async_setup_feed_view(hass)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_MERGE)
        _notify_feed_url(hass, entry)
    else:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_ACTIVITY)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _notify_feed_url(hass: HomeAssistant, entry: ConfigEntry) -> None:
    feed_path = f"/api/{DOMAIN}/{entry.entry_id}/{entry.data[CONF_TOKEN]}/feed.ics"

    try:
        base_url = get_url(hass, allow_internal=True, allow_ip=True, prefer_external=True)
    except NoURLAvailableError:
        persistent_notification.async_create(
            hass,
            (
                "Kunde inte bygga en fullständig prenumerationslänk eftersom ingen "
                "\"Home Assistant-URL\" är konfigurerad (Inställningar → System → "
                f"Nätverk). Sökvägen är:\n\n{feed_path}\n\n"
                "Sätt en extern eller lokal URL där och öppna Cal Combiner-panelen igen "
                "för att få en klickbar länk."
            ),
            title=f"Cal Combiner: {entry.data.get(CONF_NAME, 'Merged Calendar')} – ingen URL konfigurerad",
            notification_id=f"cal_combiner_{entry.entry_id}",
        )
        return

    feed_url = f"{base_url}{feed_path}"
    persistent_notification.async_create(
        hass,
        (
            f"Prenumerera på kalendern i valfri kalenderapp (Google Kalender, Apple Kalender, "
            f"Outlook m.fl. under \"Lägg till kalender via URL\"):\n\n{feed_url}\n\n"
            "Länken innehåller en hemlig token – dela den bara med dig själv/de du litar på."
        ),
        title=f"Cal Combiner: {entry.data.get(CONF_NAME, 'Merged Calendar')} är klar",
        notification_id=f"cal_combiner_{entry.entry_id}",
    )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MERGE)
    platforms = PLATFORMS_MERGE if entry_type == ENTRY_TYPE_MERGE else PLATFORMS_ACTIVITY

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_activity_coordinator", None)
    return unload_ok
