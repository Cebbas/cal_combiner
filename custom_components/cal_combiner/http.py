"""HTTP feed view so external calendar apps can subscribe via URL."""
from __future__ import annotations

from datetime import timedelta
import hmac
import logging

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_NAME, CONF_TOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)
_REGISTERED = "cal_combiner_feed_view_registered"


async def async_setup_feed_view(hass: HomeAssistant) -> None:
    if hass.data.get(_REGISTERED):
        return
    hass.data[_REGISTERED] = True
    hass.http.register_view(CalendarMergeFeedView(hass))


class CalendarMergeFeedView(HomeAssistantView):
    """Serves /api/cal_combiner/<entry_id>/<token>/feed.ics"""

    url = "/api/cal_combiner/{entry_id}/{token}/feed.ics"
    name = "api:cal_combiner:feed"
    requires_auth = False  # gated by the random token in the URL instead

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request, entry_id, token):
        from .calendar import fetch_all_events  # local import avoids circular import

        entries = self.hass.data.get(DOMAIN, {})
        entry_data = entries.get(entry_id)
        if not entry_data or "own_store" not in entry_data:
            return web.Response(status=404)

        entry = entry_data["entry"]
        if not hmac.compare_digest(token, entry.data.get(CONF_TOKEN, "")):
            return web.Response(status=403)

        now = dt_util.now()
        events, _failed = await fetch_all_events(
            self.hass,
            entry,
            entry_data["own_store"],
            now - timedelta(days=60),
            now + timedelta(days=365),
        )
        ics = _build_ics(entry.data.get(CONF_NAME, "Merged Calendar"), events)
        return web.Response(
            text=ics,
            content_type="text/calendar",
            charset="utf-8",
            headers={
                "Content-Disposition": 'inline; filename="feed.ics"',
                "Cache-Control": "no-store",
            },
        )


def _build_ics(name: str, events) -> str:
    from icalendar import Calendar, Event

    cal = Calendar()
    cal.add("prodid", "-//Cal Combiner//Home Assistant//")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", name)

    for e in events:
        ev = Event()
        ev.add("summary", e.summary)
        ev.add("dtstart", e.start)
        ev.add("dtend", e.end)
        if e.description:
            ev.add("description", e.description)
        if e.location:
            ev.add("location", e.location)
        ev.add("uid", e.uid or f"{e.summary}-{e.start}")
        cal.add_component(ev)

    return cal.to_ical().decode("utf-8")
