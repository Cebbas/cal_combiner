"""End-to-end interop test: drives the real CalDAV server with the independent
`caldav` PyPI client library, not just assertions about our own request-building
code. Verifies discovery, one-off and recurring events (incl. single-occurrence
edits via RECURRENCE-ID), and auth rejection - against the current shared-server
layout (one account/principal, one collection per merged calendar), which
replaced the old one-server-per-calendar design.

The `caldav` library is a synchronous (requests-based) HTTP client, so every
call into it runs in the executor via hass.async_add_executor_job - calling it
directly on the event loop would deadlock the very aiohttp server it's talking
to.
"""
from datetime import timedelta

import caldav
import pytest

from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cal_combiner import calendar as cc_calendar
from custom_components.cal_combiner.caldav import (
    BASE_PATH,
    async_ensure_entry_known,
    async_get_settings,
    async_register_caldav,
)
from custom_components.cal_combiner.const import (
    CONF_FILTERS,
    CONF_NAME,
    CONF_RENAME,
    CONF_SOURCES,
    CONF_TOKEN,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
async def dav_clients(hass):
    """Track every DAVClient a test creates and close its (synchronous, thread-owning)
    requests session afterwards - otherwise the connection pool's background thread
    outlives the test and trips pytest-homeassistant-custom-component's lingering-
    thread check.
    """
    created: list[caldav.DAVClient] = []
    yield created
    for client in created:
        await hass.async_add_executor_job(client.close)


async def _setup_entry(hass) -> MockConfigEntry:
    """Wire up just what CalDAV needs: http + the calendar platform's storage/coordinator
    + the CalDAV routes - not the full config-entry pipeline, which also drags in the
    `frontend` dependency (for the sidebar panel) that this test has no use for.
    """
    await async_setup_component(hass, "http", {})
    await hass.async_block_till_done()

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Familjekalender",
            CONF_TOKEN: "feed-token-unused-here",
            CONF_SOURCES: [],
            CONF_FILTERS: {},
            CONF_RENAME: {},
        },
    )
    entry.add_to_hass(hass)

    # Mirrors calendar.async_setup_entry, minus async_config_entry_first_refresh
    # (which requires the coordinator to have been built via the real config-entry
    # setup pipeline, not called directly like this test does).
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"entry": entry}
    store = cc_calendar.OwnCalendarStore(hass, entry.entry_id)
    await store.async_load()
    hass.data[DOMAIN][entry.entry_id]["own_store"] = store
    coordinator = cc_calendar.MergedCalendarCoordinator(hass, entry, store)
    await coordinator.async_refresh()
    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator

    async_register_caldav(hass)
    await async_ensure_entry_known(hass, entry.entry_id)
    return entry


async def _dav_client(hass, aiohttp_client, entry: MockConfigEntry, dav_clients) -> caldav.DAVClient:
    client = await aiohttp_client(hass.http.app)
    base = str(client.make_url("/")).rstrip("/")
    settings = await async_get_settings(hass)
    dav = caldav.DAVClient(url=f"{base}{BASE_PATH}/", username="familj", password=settings["token"])
    dav_clients.append(dav)
    return dav


async def test_discovery_lists_the_merged_calendar_as_a_collection(hass, aiohttp_client, socket_enabled, dav_clients):
    entry = await _setup_entry(hass)
    dav = await _dav_client(hass, aiohttp_client, entry, dav_clients)

    def _discover():
        principal = dav.principal()
        return [c.get_display_name() for c in principal.calendars()]

    names = await hass.async_add_executor_job(_discover)
    assert names == ["Familjekalender"]


async def test_wrong_password_is_rejected(hass, aiohttp_client, socket_enabled, dav_clients):
    entry = await _setup_entry(hass)
    client = await aiohttp_client(hass.http.app)
    base = str(client.make_url("/")).rstrip("/")
    dav = caldav.DAVClient(url=f"{base}{BASE_PATH}/", username="familj", password="wrong-password")
    dav_clients.append(dav)

    def _discover():
        return dav.principal()

    with pytest.raises(caldav.lib.error.AuthorizationError):
        await hass.async_add_executor_job(_discover)


async def test_create_list_update_delete_single_event(hass, aiohttp_client, socket_enabled, dav_clients):
    entry = await _setup_entry(hass)
    dav = await _dav_client(hass, aiohttp_client, entry, dav_clients)

    now = dt_util.now()
    start = now.replace(microsecond=0) + timedelta(days=1)
    end = start + timedelta(hours=1)

    def _roundtrip():
        calendar = dav.principal().calendars()[0]

        event = calendar.save_event(
            dtstart=start, dtend=end, summary="Tandläkare", location="Tandvården"
        )
        uid = str(event.icalendar_component["uid"])

        found = calendar.events()
        assert any(str(e.icalendar_component["uid"]) == uid for e in found)

        fetched = calendar.event_by_uid(uid)
        fetched.icalendar_component["summary"] = "Tandläkare (flyttad)"
        fetched.save()

        refetched = calendar.event_by_uid(uid)
        assert str(refetched.icalendar_component["summary"]) == "Tandläkare (flyttad)"

        refetched.delete()
        return uid

    uid = await hass.async_add_executor_job(_roundtrip)

    def _confirm_gone():
        calendar = dav.principal().calendars()[0]
        with pytest.raises(caldav.lib.error.NotFoundError):
            calendar.event_by_uid(uid)

    await hass.async_add_executor_job(_confirm_gone)


async def test_recurring_event_and_single_occurrence_edit(hass, aiohttp_client, socket_enabled, dav_clients):
    entry = await _setup_entry(hass)
    dav = await _dav_client(hass, aiohttp_client, entry, dav_clients)

    now = dt_util.now()
    start = now.replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=(7 - now.weekday()))
    end = start + timedelta(hours=1)

    def _roundtrip():
        calendar = dav.principal().calendars()[0]

        event = calendar.save_event(
            dtstart=start,
            dtend=end,
            summary="Fotbollsträning",
            rrule={"FREQ": "WEEKLY", "COUNT": 3},
        )
        uid = str(event.icalendar_component["uid"])

        # Fetch the master and confirm the RRULE round-tripped.
        master = calendar.event_by_uid(uid)
        vevents = list(master.icalendar_instance.walk("VEVENT"))
        assert any(v.get("rrule") for v in vevents)

        # Edit a single occurrence: PUT back master + one override VEVENT
        # sharing the uid, with RECURRENCE-ID set on the override.
        second_occurrence = start + timedelta(weeks=1)
        cal = master.icalendar_instance
        components = list(cal.walk("VEVENT"))
        base_vevent = components[0]

        from icalendar import Event as ICalEvent

        override = ICalEvent()
        for key in ("uid", "dtstart", "dtend"):
            override[key] = base_vevent[key]
        override["recurrence-id"] = base_vevent["dtstart"].__class__(second_occurrence)
        override["dtstart"] = base_vevent["dtstart"].__class__(second_occurrence)
        override["dtend"] = base_vevent["dtend"].__class__(second_occurrence + timedelta(hours=1))
        override["summary"] = "Cupmatch"
        cal.add_component(override)

        master.icalendar_instance = cal
        master.save()

        refetched = calendar.event_by_uid(uid)
        summaries = {
            str(v.get("recurrence-id").dt) if v.get("recurrence-id") else "master": str(v["summary"])
            for v in refetched.icalendar_instance.walk("VEVENT")
        }
        assert "Cupmatch" in summaries.values()
        return uid

    uid = await hass.async_add_executor_job(_roundtrip)
    assert uid
