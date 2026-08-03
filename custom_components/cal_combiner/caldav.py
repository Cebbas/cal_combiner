"""A minimal CalDAV server for two-way sync from apps that support it.

Google Calendar has no "add external CalDAV account" feature in any of its
apps (web, iOS, Android) - it can only subscribe read-only to the ICS feed
(see http.py) or import a static .ics once. That's a Google product
limitation with no workaround. Apple Calendar (macOS/iOS), Thunderbird, and
Android via DAVx5 all support adding a real CalDAV account, which is what
this gives them: create/edit/delete straight from the calendar app.

Implements the practical subset of RFC 4791 those clients actually exercise:
OPTIONS, PROPFIND (a fixed, generous property set rather than full dynamic
per-request negotiation - clients tolerate extra properties they didn't ask
for, and this avoids writing a general-purpose property-request parser),
REPORT calendar-query (a full listing; sync-collection is a possible later
addition - see IDEAS.md), and GET/PUT/DELETE for individual object
resources.

Resource model: each entry has one collection at
`/api/cal_combiner/{entry_id}/dav` which doubles as the principal,
calendar-home-set, and the one calendar collection (a standard
simplification for a single-calendar personal CalDAV account - clients
handle a self-referential hierarchy fine). Each event uid becomes an object
resource at `.../dav/{quoted-uid}.ics`.

For the calendar's own store, a recurring event's master VEVENT and any
single-occurrence overrides are bundled as multiple VEVENTs sharing one uid
in one resource - that's how iCalendar actually represents recurrence, not
one resource per occurrence. Events merged in from external source calendars
are exposed too (read, and edits are forwarded to the real source, reusing
the exact routing `calendar.py` already uses for Home Assistant's own
dashboard) as flat one-off resources, since `calendar.get_events` already
hands those to us pre-expanded - we never see their own RRULE, if any.

Auth is HTTP Basic (any username, password = the entry's existing secret
token, same one already used for the ICS feed) since that's the literal
username/password form Apple Calendar's "Other -> Add CalDAV Account" dialog
and DAVx5 require - there's no "paste a secret URL" flow like webcal
subscription for CalDAV account setup.
"""
from __future__ import annotations

import base64
from datetime import timedelta
import hashlib
import hmac
import logging
from typing import Any
from urllib.parse import quote, unquote
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

from aiohttp import hdrs, web
from icalendar import Calendar
from icalendar import Event as ICalEvent

from homeassistant.components.calendar import CalendarEvent
from homeassistant.components.http import KEY_HASS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .calendar import _parse_merged_uid, delete_event, fetch_merged_events, update_event
from .const import CONF_FILTERS, CONF_NAME, CONF_SOURCES, CONF_TOKEN, DOMAIN
from .own_calendar import OwnCalendarStore, _as_datetime, _parse as parse_dt

_LOGGER = logging.getLogger(__name__)
_REGISTERED = "cal_combiner_caldav_registered"

BASE_PATH = "/api/cal_combiner/{entry_id}/dav"
OBJECT_PATH = "/api/cal_combiner/{entry_id}/dav/{uid}.ics"

# How far to look when a request carries no explicit time-range (a plain GET
# on one resource, or a REPORT/PROPFIND without a parseable filter).
_LOOKUP_PAST = timedelta(days=400)
_LOOKUP_FUTURE = timedelta(days=730)

DAV_NS = "DAV:"
CALDAV_NS = "urn:ietf:params:xml:ns:caldav"
CS_NS = "http://calendarserver.org/ns/"


# ---- auth / entry resolution ----


def _entry_data(hass: HomeAssistant, entry_id: str) -> dict | None:
    return hass.data.get(DOMAIN, {}).get(entry_id)


def _check_auth(request: web.Request, entry) -> bool:
    header = request.headers.get(hdrs.AUTHORIZATION, "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    _username, _, password = decoded.partition(":")
    token = entry.data.get(CONF_TOKEN, "")
    return bool(token) and hmac.compare_digest(password, token)


def _unauthorized() -> web.Response:
    return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="Cal Combiner"'})


async def _authorize(request: web.Request):
    """Common preamble for every handler: resolve hass/entry/store, check auth.

    Returns (hass, entry, store) on success, or a web.Response to return as-is.
    """
    hass = request.app[KEY_HASS]
    entry_id = request.match_info["entry_id"]
    data = _entry_data(hass, entry_id)
    if not data or "own_store" not in data:
        return web.Response(status=404)
    entry = data["entry"]
    if not _check_auth(request, entry):
        return _unauthorized()
    return hass, entry, data["own_store"]


# ---- uid / href helpers ----


def _collection_href(entry_id: str) -> str:
    return BASE_PATH.format(entry_id=entry_id) + "/"


def _object_href(entry_id: str, uid: str) -> str:
    return OBJECT_PATH.format(entry_id=entry_id, uid=quote(uid, safe=""))


def _etag_for_item(item: dict[str, Any]) -> str:
    payload = "|".join(
        str(item.get(k))
        for k in ("uid", "summary", "description", "location", "start", "end", "rrule", "exdates", "overrides")
    )
    return hashlib.sha1(payload.encode()).hexdigest()


def _etag_for_event(ev: CalendarEvent) -> str:
    payload = f"{ev.uid}|{ev.summary}|{ev.start}|{ev.end}|{ev.description}|{ev.location}"
    return hashlib.sha1(payload.encode()).hexdigest()


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ---- iCalendar serialization ----


def _own_item_to_ics(item: dict[str, Any]) -> str:
    cal = Calendar()
    cal.add("prodid", "-//Cal Combiner//Home Assistant//")
    cal.add("version", "2.0")

    master_start = parse_dt(item["start"])
    master_end = parse_dt(item["end"])
    rrule = item.get("rrule")

    master = ICalEvent()
    master.add("uid", item["uid"])
    master.add("summary", item.get("summary") or "")
    master.add("dtstart", master_start)
    master.add("dtend", master_end)
    if item.get("description"):
        master.add("description", item["description"])
    if item.get("location"):
        master.add("location", item["location"])
    if rrule:
        master.add("rrule", rrule)
        for exd in item.get("exdates") or []:
            master.add("exdate", parse_dt(exd))
    cal.add_component(master)

    if rrule:
        duration = _as_datetime(master_end) - _as_datetime(master_start)
        for occ_key, override in (item.get("overrides") or {}).items():
            ov = ICalEvent()
            ov.add("uid", item["uid"])
            ov.add("recurrence-id", parse_dt(occ_key))
            occ_start = parse_dt(override["start"]) if "start" in override else parse_dt(occ_key)
            occ_end = parse_dt(override["end"]) if "end" in override else occ_start + duration
            ov.add("dtstart", occ_start)
            ov.add("dtend", occ_end)
            ov.add("summary", override.get("summary", item.get("summary")) or "")
            description = override.get("description", item.get("description"))
            if description:
                ov.add("description", description)
            location = override.get("location", item.get("location"))
            if location:
                ov.add("location", location)
            cal.add_component(ov)

    return cal.to_ical().decode("utf-8")


def _external_event_to_ics(ev: CalendarEvent) -> str:
    cal = Calendar()
    cal.add("prodid", "-//Cal Combiner//Home Assistant//")
    cal.add("version", "2.0")
    vevent = ICalEvent()
    vevent.add("uid", ev.uid)
    vevent.add("summary", ev.summary or "")
    vevent.add("dtstart", ev.start)
    vevent.add("dtend", ev.end)
    if ev.description:
        vevent.add("description", ev.description)
    if ev.location:
        vevent.add("location", ev.location)
    cal.add_component(vevent)
    return cal.to_ical().decode("utf-8")


# ---- XML building ----


def _collection_propstat_xml(href: str, name: str, ctag: int) -> str:
    href_x, name_x = xml_escape(href), xml_escape(name)
    return f"""<D:response>
<D:href>{href_x}</D:href>
<D:propstat><D:prop>
<D:resourcetype><D:collection/><C:calendar/></D:resourcetype>
<D:displayname>{name_x}</D:displayname>
<D:current-user-principal><D:href>{href_x}</D:href></D:current-user-principal>
<C:calendar-home-set><D:href>{href_x}</D:href></C:calendar-home-set>
<C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>
<CS:getctag>{ctag}</CS:getctag>
<D:supported-report-set><D:supported-report><D:report><C:calendar-query/></D:report></D:supported-report></D:supported-report-set>
</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
</D:response>"""


def _object_propstat_xml(href: str, etag: str) -> str:
    href_x = xml_escape(href)
    return f"""<D:response>
<D:href>{href_x}</D:href>
<D:propstat><D:prop>
<D:getetag>"{etag}"</D:getetag>
<D:resourcetype/>
</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
</D:response>"""


def _object_data_xml(href: str, etag: str, ics_text: str) -> str:
    href_x, ics_x = xml_escape(href), xml_escape(ics_text)
    return f"""<D:response>
<D:href>{href_x}</D:href>
<D:propstat><D:prop>
<D:getetag>"{etag}"</D:getetag>
<C:calendar-data>{ics_x}</C:calendar-data>
</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
</D:response>"""


def _multistatus(inner: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<D:multistatus xmlns:D="{DAV_NS}" xmlns:C="{CALDAV_NS}" xmlns:CS="{CS_NS}">'
        + inner
        + "</D:multistatus>"
    )


def _parse_time_range(body: bytes):
    now = dt_util.now()
    default_start, default_end = now - _LOOKUP_PAST, now + _LOOKUP_FUTURE
    if not body:
        return default_start, default_end
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return default_start, default_end
    for el in root.iter():
        if el.tag.endswith("time-range"):
            start = dt_util.parse_datetime(el.get("start") or "")
            end = dt_util.parse_datetime(el.get("end") or "")
            if start and end:
                return start, end
    return default_start, default_end


# ---- HTTP method handlers ----


async def handle_options(request: web.Request) -> web.Response:
    return web.Response(
        status=200,
        headers={
            "DAV": "1, 2, 3, calendar-access",
            "Allow": "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, REPORT",
        },
    )


async def handle_propfind(request: web.Request) -> web.Response:
    auth = await _authorize(request)
    if isinstance(auth, web.Response):
        return auth
    hass, entry, store = auth
    entry_id = request.match_info["entry_id"]
    depth = request.headers.get("Depth", "0")

    href = _collection_href(entry_id)
    responses = [_collection_propstat_xml(href, entry.data.get(CONF_NAME, "Cal Combiner"), store.ctag)]

    if depth == "1":
        now = dt_util.now()
        start, end = now - _LOOKUP_PAST, now + _LOOKUP_FUTURE
        for item in store.masters_overlapping(start, end):
            responses.append(_object_propstat_xml(_object_href(entry_id, item["uid"]), _etag_for_item(item)))
        external_events, _failed = await fetch_merged_events(
            hass, entry.data.get(CONF_SOURCES, []), start, end, entry.data.get(CONF_FILTERS, {})
        )
        for ev in external_events:
            responses.append(_object_propstat_xml(_object_href(entry_id, ev.uid), _etag_for_event(ev)))

    return web.Response(status=207, content_type="application/xml", charset="utf-8", text=_multistatus("".join(responses)))


async def handle_report(request: web.Request) -> web.Response:
    auth = await _authorize(request)
    if isinstance(auth, web.Response):
        return auth
    hass, entry, store = auth
    entry_id = request.match_info["entry_id"]

    body = await request.read()
    start, end = _parse_time_range(body)

    responses = []
    for item in store.masters_overlapping(start, end):
        responses.append(
            _object_data_xml(_object_href(entry_id, item["uid"]), _etag_for_item(item), _own_item_to_ics(item))
        )
    external_events, _failed = await fetch_merged_events(
        hass, entry.data.get(CONF_SOURCES, []), start, end, entry.data.get(CONF_FILTERS, {})
    )
    for ev in external_events:
        responses.append(
            _object_data_xml(_object_href(entry_id, ev.uid), _etag_for_event(ev), _external_event_to_ics(ev))
        )

    return web.Response(status=207, content_type="application/xml", charset="utf-8", text=_multistatus("".join(responses)))


async def handle_get(request: web.Request) -> web.Response:
    auth = await _authorize(request)
    if isinstance(auth, web.Response):
        return auth
    hass, entry, store = auth
    uid = unquote(request.match_info["uid"])

    item = store.get_master(uid)
    if item is not None:
        return web.Response(
            text=_own_item_to_ics(item),
            content_type="text/calendar",
            charset="utf-8",
            headers={"ETag": f'"{_etag_for_item(item)}"'},
        )

    if _parse_merged_uid(uid) is not None:
        now = dt_util.now()
        external_events, _failed = await fetch_merged_events(
            hass, entry.data.get(CONF_SOURCES, []), now - _LOOKUP_PAST, now + _LOOKUP_FUTURE, entry.data.get(CONF_FILTERS, {})
        )
        match = next((e for e in external_events if e.uid == uid), None)
        if match is not None:
            return web.Response(
                text=_external_event_to_ics(match),
                content_type="text/calendar",
                charset="utf-8",
                headers={"ETag": f'"{_etag_for_event(match)}"'},
            )

    return web.Response(status=404)


async def handle_put(request: web.Request) -> web.Response:
    auth = await _authorize(request)
    if isinstance(auth, web.Response):
        return auth
    hass, entry, store = auth
    uid = unquote(request.match_info["uid"])

    body = await request.text()
    try:
        parsed = Calendar.from_ical(body)
    except ValueError as err:
        return web.Response(status=400, text=f"Kunde inte tolka iCalendar-data: {err}")

    components = list(parsed.walk("VEVENT"))
    if not components:
        return web.Response(status=400, text="Ingen VEVENT hittades i iCalendar-datan")

    # An existing external-sourced event: forward the edit to its real source,
    # same as editing it via Home Assistant's own calendar dashboard would.
    # New events always go to the own store - mirroring create_event's rule.
    if store.get_master(uid) is None and _parse_merged_uid(uid) is not None:
        master = components[0]
        event_dict: dict[str, Any] = {
            "summary": str(master.get("summary", "")),
            "dtstart": master.get("dtstart").dt,
            "dtend": master.get("dtend").dt,
        }
        if master.get("description"):
            event_dict["description"] = str(master.get("description"))
        if master.get("location"):
            event_dict["location"] = str(master.get("location"))
        try:
            await update_event(hass, entry, store, uid, event_dict)
        except HomeAssistantError as err:
            return web.Response(status=409, text=str(err))
        return web.Response(status=204)

    master = next((c for c in components if c.get("recurrence-id") is None), components[0])
    override_components = [c for c in components if c.get("recurrence-id") is not None]

    summary = str(master.get("summary", ""))
    description = str(master.get("description")) if master.get("description") else None
    location = str(master.get("location")) if master.get("location") else None
    dtstart = master.get("dtstart").dt
    dtend = master.get("dtend").dt
    rrule_prop = master.get("rrule")
    rrule = rrule_prop.to_ical().decode() if rrule_prop else None
    exdates = [
        d.dt.isoformat() for wrapper in _as_list(master.get("exdate")) for d in wrapper.dts
    ]

    overrides: dict[str, dict[str, Any]] = {}
    for ov in override_components:
        occ_key = ov.get("recurrence-id").dt.isoformat()
        override: dict[str, Any] = {"summary": str(ov.get("summary", summary))}
        if ov.get("description"):
            override["description"] = str(ov.get("description"))
        if ov.get("location"):
            override["location"] = str(ov.get("location"))
        if ov.get("dtstart"):
            override["start"] = ov.get("dtstart").dt.isoformat()
        if ov.get("dtend"):
            override["end"] = ov.get("dtend").dt.isoformat()
        overrides[occ_key] = override

    await store.async_put_master(
        uid,
        summary=summary,
        description=description,
        location=location,
        start=dtstart,
        end=dtend,
        rrule=rrule,
        exdates=exdates,
        overrides=overrides,
    )
    return web.Response(status=201)


async def handle_delete(request: web.Request) -> web.Response:
    auth = await _authorize(request)
    if isinstance(auth, web.Response):
        return auth
    hass, entry, store = auth
    uid = unquote(request.match_info["uid"])

    if store.get_master(uid) is not None:
        await store.async_delete_event(uid)
        return web.Response(status=204)

    if _parse_merged_uid(uid) is not None:
        try:
            await delete_event(hass, entry, store, uid)
        except HomeAssistantError as err:
            return web.Response(status=404, text=str(err))
        return web.Response(status=204)

    return web.Response(status=404)


def async_register_caldav(hass: HomeAssistant) -> None:
    """Register the CalDAV routes directly on the aiohttp router.

    HomeAssistantView.register() only wires up a fixed method allowlist
    (get/post/delete/put/patch/head/options) - PROPFIND/REPORT aren't in it,
    so a normal view subclass can't handle them. hass.http.app is a real
    aiohttp.web.Application, so routes for the WebDAV-specific methods (and,
    for consistency, everything else here too) are added directly on its
    router instead. Home Assistant's own auth middleware only *sets*
    request[KEY_AUTHENTICATED] based on Bearer tokens/signed URLs and never
    itself rejects a request - enforcement is normally the view wrapper's
    job, which we're bypassing, so every handler above does its own Basic
    Auth check via _authorize().
    """
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True

    router = hass.http.app.router
    # Collections conventionally have a trailing slash, and clients aren't
    # consistent about whether they keep it, so both variants are registered -
    # aiohttp treats ".../dav" and ".../dav/" as distinct routes with no
    # automatic normalization.
    for base in (BASE_PATH, f"{BASE_PATH}/"):
        router.add_route("OPTIONS", base, handle_options)
        router.add_route("PROPFIND", base, handle_propfind)
        router.add_route("REPORT", base, handle_report)
    router.add_route("OPTIONS", OBJECT_PATH, handle_options)
    router.add_route("GET", OBJECT_PATH, handle_get)
    router.add_route("PUT", OBJECT_PATH, handle_put)
    router.add_route("DELETE", OBJECT_PATH, handle_delete)


def caldav_url(hass: HomeAssistant, entry_id: str) -> str | None:
    """Base URL for the CalDAV account (Server URL field in the calendar app)."""
    from homeassistant.helpers.network import NoURLAvailableError, get_url

    try:
        base_url = get_url(hass, allow_internal=True, allow_ip=True, prefer_external=True)
    except NoURLAvailableError:
        return None
    return f"{base_url}{BASE_PATH.format(entry_id=entry_id)}/"
