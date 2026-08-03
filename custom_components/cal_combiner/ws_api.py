"""Websocket API used by the Cal Combiner sidebar panel."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .activity_log import async_clear, async_get_entries, async_log
from .caldav import caldav_url
from .const import (
    CONF_CREATE_BINARY,
    CONF_CREATE_SENSOR,
    CONF_ENTRY_TYPE,
    CONF_FILTER,
    CONF_FILTERS,
    CONF_ICON,
    CONF_NAME,
    CONF_PICTURE,
    CONF_SOURCES,
    CONF_TOKEN,
    CONF_TRIGGER_MODE,
    DOMAIN,
    ENTRY_TYPE_ACTIVITY,
    ENTRY_TYPE_MERGE,
    TRIGGER_MODE_ACTIVE,
)


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
        "feed_url": feed_url,
        "feed_url_webcal": feed_url.replace("https://", "webcal://").replace("http://", "webcal://")
        if feed_url
        else None,
        "caldav_url": caldav_url(hass, entry.entry_id),
        "caldav_password": entry.data.get(CONF_TOKEN),
    }


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_entries"})
@websocket_api.async_response
async def ws_list_entries(hass: HomeAssistant, connection, msg):
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MERGE) == ENTRY_TYPE_MERGE
    ]
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

    filters = dict(entry.data.get(CONF_FILTERS, {}))
    new_filter = msg.get("filter")
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


def _activity_entry_to_dict(entry) -> dict:
    return {
        "entry_id": entry.entry_id,
        "name": entry.data.get(CONF_NAME),
        "sources": entry.data.get(CONF_SOURCES, []),
        "icon": entry.data.get(CONF_ICON),
        "picture": entry.data.get(CONF_PICTURE),
        "filter": entry.data.get(CONF_FILTER),
        "trigger_mode": entry.data.get(CONF_TRIGGER_MODE, TRIGGER_MODE_ACTIVE),
        "create_binary_sensor": entry.data.get(CONF_CREATE_BINARY, True),
        "create_sensor": entry.data.get(CONF_CREATE_SENSOR, True),
    }


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_activity_sensors"})
@websocket_api.async_response
async def ws_list_activity_sensors(hass: HomeAssistant, connection, msg):
    entries = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ACTIVITY
    ]
    connection.send_result(
        msg["id"], {"entries": [_activity_entry_to_dict(e) for e in entries]}
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/create_activity_sensor",
        vol.Required("name"): str,
        vol.Required("sources"): [str],
        vol.Optional("icon"): vol.Any(str, None),
        vol.Optional("picture"): vol.Any(str, None),
        vol.Optional("field", default="any"): str,
        vol.Optional("include", default=""): str,
        vol.Optional("exclude", default=""): str,
        vol.Optional("use_regex", default=False): bool,
        vol.Optional("case_sensitive", default=False): bool,
        vol.Optional("trigger_mode", default=TRIGGER_MODE_ACTIVE): str,
        vol.Optional("create_binary_sensor", default=True): bool,
        vol.Optional("create_sensor", default=True): bool,
    }
)
@websocket_api.async_response
async def ws_create_activity_sensor(hass: HomeAssistant, connection, msg):
    if not msg["sources"]:
        connection.send_error(msg["id"], "no_sources", "Välj minst en källkalender")
        return
    if not (msg["create_binary_sensor"] or msg["create_sensor"]):
        connection.send_error(msg["id"], "no_sensor_type", "Välj minst en sensor-typ")
        return

    payload = {k: v for k, v in msg.items() if k != "type"}
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "activity_sensor"}, data=payload
    )
    if result.get("type") == "form":
        connection.send_error(msg["id"], "invalid_input", "Kunde inte skapa sensorn")
        return
    entry_id = result["result"].entry_id
    await async_log(hass, entry_id, "Sensor skapad")
    connection.send_result(msg["id"], {"ok": True, "entry_id": entry_id})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/update_activity_sensor",
        vol.Required("entry_id"): str,
        vol.Required("name"): str,
        vol.Required("sources"): [str],
        vol.Optional("icon"): vol.Any(str, None),
        vol.Optional("picture"): vol.Any(str, None),
        vol.Optional("field", default="any"): str,
        vol.Optional("include", default=""): str,
        vol.Optional("exclude", default=""): str,
        vol.Optional("use_regex", default=False): bool,
        vol.Optional("case_sensitive", default=False): bool,
        vol.Optional("trigger_mode", default=TRIGGER_MODE_ACTIVE): str,
        vol.Optional("create_binary_sensor", default=True): bool,
        vol.Optional("create_sensor", default=True): bool,
    }
)
@websocket_api.async_response
async def ws_update_activity_sensor(hass: HomeAssistant, connection, msg):
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_ACTIVITY:
        connection.send_error(msg["id"], "not_found", "Hittade inte sensorn")
        return
    if not msg["sources"]:
        connection.send_error(msg["id"], "no_sources", "Välj minst en källkalender")
        return
    if not (msg["create_binary_sensor"] or msg["create_sensor"]):
        connection.send_error(msg["id"], "no_sensor_type", "Välj minst en sensor-typ")
        return

    include = [w.strip() for w in msg["include"].split(",") if w.strip()]
    exclude = [w.strip() for w in msg["exclude"].split(",") if w.strip()]
    rule = (
        {
            "field": msg["field"],
            "include": include,
            "exclude": exclude,
            "use_regex": msg["use_regex"],
            "case_sensitive": msg["case_sensitive"],
        }
        if (include or exclude)
        else None
    )

    changes = []
    if msg["name"] != entry.data.get(CONF_NAME):
        changes.append(f'namn ändrat till "{msg["name"]}"')
    if set(msg["sources"]) != set(entry.data.get(CONF_SOURCES, [])):
        changes.append("källor uppdaterade")
    if rule != entry.data.get(CONF_FILTER):
        changes.append("filter uppdaterat")
    if msg["trigger_mode"] != entry.data.get(CONF_TRIGGER_MODE, TRIGGER_MODE_ACTIVE):
        changes.append("triggerläge ändrat")
    if msg.get("icon") != entry.data.get(CONF_ICON):
        changes.append("ikon ändrad")
    if msg.get("picture") != entry.data.get(CONF_PICTURE):
        changes.append("bild ändrad")

    new_data = dict(entry.data)
    new_data[CONF_NAME] = msg["name"]
    new_data[CONF_SOURCES] = msg["sources"]
    new_data[CONF_ICON] = msg.get("icon")
    new_data[CONF_PICTURE] = msg.get("picture")
    new_data[CONF_FILTER] = rule
    new_data[CONF_TRIGGER_MODE] = msg["trigger_mode"]
    new_data[CONF_CREATE_BINARY] = msg["create_binary_sensor"]
    new_data[CONF_CREATE_SENSOR] = msg["create_sensor"]
    hass.config_entries.async_update_entry(entry, data=new_data, title=msg["name"])
    await hass.config_entries.async_reload(entry.entry_id)
    if changes:
        await async_log(hass, entry.entry_id, "Uppdaterad: " + "; ".join(changes))
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/delete_entry", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_delete_entry(hass: HomeAssistant, connection, msg):
    """Deletes any Cal Combiner entry, merged calendar or activity sensor alike."""
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "not_found", "Hittade inte kalendern")
        return
    await hass.config_entries.async_remove(msg["entry_id"])
    await async_clear(hass, msg["entry_id"])
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_activity_log", vol.Required("entry_id"): str}
)
@websocket_api.async_response
async def ws_get_activity_log(hass: HomeAssistant, connection, msg):
    entries = await async_get_entries(hass, msg["entry_id"])
    connection.send_result(msg["id"], {"entries": entries})


def async_register_ws_api(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_list_entries)
    websocket_api.async_register_command(hass, ws_list_calendars)
    websocket_api.async_register_command(hass, ws_create_entry)
    websocket_api.async_register_command(hass, ws_update_entry)
    websocket_api.async_register_command(hass, ws_update_filter)
    websocket_api.async_register_command(hass, ws_delete_entry)
    websocket_api.async_register_command(hass, ws_list_activity_sensors)
    websocket_api.async_register_command(hass, ws_create_activity_sensor)
    websocket_api.async_register_command(hass, ws_update_activity_sensor)
    websocket_api.async_register_command(hass, ws_get_activity_log)
