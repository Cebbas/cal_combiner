"""Websocket API used by the Cal Combiner sidebar panel."""
from __future__ import annotations

from datetime import timedelta
import re

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from . import caldav
from .activity_log import async_clear, async_get_entries, async_log
from .calendar import fetch_merged_events
from .const import (
    CONF_FILTERS,
    CONF_ICON,
    CONF_NAME,
    CONF_PICTURE,
    CONF_RENAME,
    CONF_SOURCES,
    CONF_TOKEN,
    DOMAIN,
)

RENAME_RULE_SCHEMA = {
    vol.Required("pattern"): str,
    vol.Optional("replacement", default=""): str,
    vol.Optional("field", default="summary"): vol.In(["summary", "description", "location"]),
}


def _check_regex_patterns(patterns: list[str]) -> str | None:
    """Compile-check a batch of user-supplied regex patterns; returns an error message, if any."""
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as err:
            return f"Ogiltigt regex-mönster {pattern!r}: {err}"
    return None


def _feed_url(hass: HomeAssistant, entry) -> str | None:
    path = f"/api/{DOMAIN}/{entry.entry_id}/{entry.data.get(CONF_TOKEN)}/feed.ics"
    try:
        base_url = get_url(hass, allow_internal=True, allow_ip=True, prefer_external=True)
    except NoURLAvailableError:
        return None
    return f"{base_url}{path}"


def _entry_to_dict(hass: HomeAssistant, entry) -> dict:
    feed_url = _feed_url(hass, entry)
    return {
        "entry_id": entry.entry_id,
        "name": entry.data.get(CONF_NAME),
        "sources": entry.data.get(CONF_SOURCES, []),
        "icon": entry.data.get(CONF_ICON),
        "picture": entry.data.get(CONF_PICTURE),
        "filters": entry.data.get(CONF_FILTERS, {}),
        "rename": entry.data.get(CONF_RENAME, {}),
        "feed_url": feed_url,
        "feed_url_webcal": feed_url.replace("https://", "webcal://").replace("http://", "webcal://")
        if feed_url
        else None,
    }


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_entries"})
@websocket_api.async_response
async def ws_list_entries(hass: HomeAssistant, connection, msg):
    entries = hass.config_entries.async_entries(DOMAIN)
    connection.send_result(msg["id"], {"entries": [_entry_to_dict(hass, e) for e in entries]})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_calendars"})
@websocket_api.async_response
async def ws_list_calendars(hass: HomeAssistant, connection, msg):
    calendars = [
        {"entity_id": state.entity_id, "name": state.attributes.get("friendly_name", state.entity_id)}
        for state in hass.states.async_all("calendar")
    ]
    calendars.sort(key=lambda c: c["name"])
    connection.send_result(msg["id"], {"calendars": calendars})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/create_entry",
        vol.Required("name"): str,
        vol.Optional("sources", default=[]): [str],
        vol.Optional("icon"): vol.Any(str, None),
        vol.Optional("picture"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_create_entry(hass: HomeAssistant, connection, msg):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "merge_calendar"},
        data={
            "name": msg["name"],
            "sources": msg["sources"],
            "icon": msg.get("icon"),
            "picture": msg.get("picture"),
        },
    )
    if result.get("type") == "form":
        connection.send_error(msg["id"], "invalid_input", "Kunde inte skapa kalendern")
        return
    entry_id = result["result"].entry_id
    await async_log(hass, entry_id, "Kalender skapad")
    connection.send_result(msg["id"], {"ok": True, "entry_id": entry_id})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/update_entry",
        vol.Required("entry_id"): str,
        vol.Required("name"): str,
        vol.Optional("sources", default=[]): [str],
        vol.Optional("icon"): vol.Any(str, None),
        vol.Optional("picture"): vol.Any(str, None),
    }
)
@websocket_api.async_response
async def ws_update_entry(hass: HomeAssistant, connection, msg):
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Hittade inte kalendern")
        return

    changes = []
    if msg["name"] != entry.data.get(CONF_NAME):
        changes.append(f'namn ändrat till "{msg["name"]}"')
    old_sources = set(entry.data.get(CONF_SOURCES, []))
    new_sources = set(msg["sources"])
    added = new_sources - old_sources
    removed = old_sources - new_sources
    if added:
        changes.append(f"källa tillagd: {', '.join(sorted(added))}")
    if removed:
        changes.append(f"källa borttagen: {', '.join(sorted(removed))}")
    if msg.get("icon") != entry.data.get(CONF_ICON):
        changes.append("ikon ändrad")
    if msg.get("picture") != entry.data.get(CONF_PICTURE):
        changes.append("bild ändrad")

    new_data = dict(entry.data)
    new_data[CONF_NAME] = msg["name"]
    new_data[CONF_SOURCES] = msg["sources"]
    new_data[CONF_ICON] = msg.get("icon")
    new_data[CONF_PICTURE] = msg.get("picture")
    hass.config_entries.async_update_entry(entry, data=new_data, title=msg["name"])
    await hass.config_entries.async_reload(entry.entry_id)
    if changes:
        await async_log(hass, entry.entry_id, "Uppdaterad: " + "; ".join(changes))
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/update_filter",
        vol.Required("entry_id"): str,
        vol.Required("source_entity_id"): str,
        vol.Optional("filter"): vol.Any(dict, None),
    }
)
@websocket_api.async_response
async def ws_update_filter(hass: HomeAssistant, connection, msg):
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Hittade inte kalendern")
        return

    new_filter = msg.get("filter")
    if new_filter and new_filter.get("use_regex"):
        error = _check_regex_patterns((new_filter.get("include") or []) + (new_filter.get("exclude") or []))
        if error:
            connection.send_error(msg["id"], "invalid_regex", error)
            return

    filters = dict(entry.data.get(CONF_FILTERS, {}))
    if new_filter:
        filters[msg["source_entity_id"]] = new_filter
    else:
        filters.pop(msg["source_entity_id"], None)

    new_data = dict(entry.data)
    new_data[CONF_FILTERS] = filters
    hass.config_entries.async_update_entry(entry, data=new_data)
    await hass.config_entries.async_reload(entry.entry_id)
    verb = "satt" if new_filter else "borttaget"
    await async_log(hass, entry.entry_id, f"Filter {verb} för {msg['source_entity_id']}")
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/update_rename",
        vol.Required("entry_id"): str,
        vol.Required("source_entity_id"): str,
        vol.Optional("rules", default=[]): [RENAME_RULE_SCHEMA],
    }
)
@websocket_api.async_response
async def ws_update_rename(hass: HomeAssistant, connection, msg):
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Hittade inte kalendern")
        return

    rules = [r for r in msg["rules"] if r.get("pattern", "").strip()]
    error = _check_regex_patterns([r["pattern"] for r in rules])
    if error:
        connection.send_error(msg["id"], "invalid_regex", error)
        return

    renames = dict(entry.data.get(CONF_RENAME, {}))
    if rules:
        renames[msg["source_entity_id"]] = rules
    else:
        renames.pop(msg["source_entity_id"], None)

    new_data = dict(entry.data)
    new_data[CONF_RENAME] = renames
    hass.config_entries.async_update_entry(entry, data=new_data)
    await hass.config_entries.async_reload(entry.entry_id)
    verb = "satt" if rules else "borttaget"
    await async_log(hass, entry.entry_id, f"Namnbyte {verb} för {msg['source_entity_id']}")
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/delete_entry", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_delete_entry(hass: HomeAssistant, connection, msg):
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Hittade inte kalendern")
        return
    own_store = hass.data.get(DOMAIN, {}).get(msg["entry_id"], {}).get("own_store")
    await hass.config_entries.async_remove(msg["entry_id"])
    if own_store is not None:
        await own_store.async_remove()
    await async_clear(hass, msg["entry_id"])
    await caldav.async_forget_entry(hass, msg["entry_id"])
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/preview_source",
        vol.Required("source_entity_id"): str,
        vol.Optional("filter"): vol.Any(dict, None),
        vol.Optional("rules", default=[]): [RENAME_RULE_SCHEMA],
    }
)
@websocket_api.async_response
async def ws_preview_source(hass: HomeAssistant, connection, msg):
    """Show what a not-yet-saved filter/rename combo would do to a source's real upcoming events."""
    new_filter = msg.get("filter")
    if new_filter and new_filter.get("use_regex"):
        error = _check_regex_patterns((new_filter.get("include") or []) + (new_filter.get("exclude") or []))
        if error:
            connection.send_error(msg["id"], "invalid_regex", error)
            return

    rules = [r for r in msg["rules"] if r.get("pattern", "").strip()]
    error = _check_regex_patterns([r["pattern"] for r in rules])
    if error:
        connection.send_error(msg["id"], "invalid_regex", error)
        return

    entity_id = msg["source_entity_id"]
    now = dt_util.now()
    start, end = now - timedelta(days=1), now + timedelta(days=60)
    filters = {entity_id: new_filter} if new_filter else {}

    # Fetched twice (with vs. without the rename rules) rather than diffing
    # rename results after the fact, since that's the exact same code path
    # (fetch_merged_events) the real merged calendar uses - no risk of the
    # preview drifting from what saving would actually produce.
    before_events, failed = await fetch_merged_events(hass, [entity_id], start, end, filters, {})
    after_events, _failed = await fetch_merged_events(
        hass, [entity_id], start, end, filters, {entity_id: rules} if rules else {}
    )

    def _fmt(value) -> str:
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    events = [
        {"start": _fmt(before.start), "before": before.summary, "after": after.summary}
        for before, after in zip(before_events, after_events)
    ]
    connection.send_result(msg["id"], {"events": events[:15], "failed": bool(failed)})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/sync_now", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_sync_now(hass: HomeAssistant, connection, msg):
    data = hass.data.get(DOMAIN, {}).get(msg["entry_id"])
    coordinator = data.get("coordinator") if data else None
    if coordinator is None:
        connection.send_error(msg["id"], "not_found", "Hittade inte kalendern")
        return
    await coordinator.async_refresh()
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_activity_log", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_get_activity_log(hass: HomeAssistant, connection, msg):
    entries = await async_get_entries(hass, msg["entry_id"])
    connection.send_result(msg["id"], {"entries": entries})


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_caldav_settings"})
@websocket_api.async_response
async def ws_get_caldav_settings(hass: HomeAssistant, connection, msg):
    settings = await caldav.async_get_settings(hass)
    entries = hass.config_entries.async_entries(DOMAIN)
    connection.send_result(
        msg["id"],
        {
            "server_url": caldav.caldav_base_url(hass),
            "password": settings["token"],
            "included": settings["included"],
            "calendars": [{"entry_id": e.entry_id, "name": e.data.get(CONF_NAME)} for e in entries],
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/set_caldav_included", vol.Required("included"): [str]}
)
@websocket_api.async_response
async def ws_set_caldav_included(hass: HomeAssistant, connection, msg):
    await caldav.async_set_included(hass, msg["included"])
    connection.send_result(msg["id"], {"ok": True})


def async_register_ws_api(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_list_entries)
    websocket_api.async_register_command(hass, ws_list_calendars)
    websocket_api.async_register_command(hass, ws_create_entry)
    websocket_api.async_register_command(hass, ws_update_entry)
    websocket_api.async_register_command(hass, ws_update_filter)
    websocket_api.async_register_command(hass, ws_update_rename)
    websocket_api.async_register_command(hass, ws_preview_source)
    websocket_api.async_register_command(hass, ws_sync_now)
    websocket_api.async_register_command(hass, ws_delete_entry)
    websocket_api.async_register_command(hass, ws_get_activity_log)
    websocket_api.async_register_command(hass, ws_get_caldav_settings)
    websocket_api.async_register_command(hass, ws_set_caldav_included)
