"""Calendar platform for Cal Combiner."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import hashlib
import logging
import re

from homeassistant.components.calendar import (
    DOMAIN as CALENDAR_DOMAIN,
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .activity_log import async_log
from .const import (
    CONF_FILTERS,
    CONF_ICON,
    CONF_NAME,
    CONF_PICTURE,
    CONF_RENAME,
    CONF_SOURCES,
    DEFAULT_MERGE_ICON,
    DOMAIN,
)
from .own_calendar import OwnCalendarStore

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=5)
# How many consecutive failed polls a source needs before it's surfaced as a
# repair issue - a single blip (a flaky proxy, a momentary timeout) shouldn't
# raise a user-visible issue on every poll; it should just quietly retry.
FAILURE_THRESHOLD = 2
UID_SEPARATOR = "::"
# Marks a merged uid as belonging to the calendar's own store rather than an
# external source entity_id (which can never collide with this, since entity
# ids always contain a domain and a dot, e.g. "calendar.foo").
OWN_SOURCE_MARKER = "__own__"
# Appended (with the occurrence's recurrence_id) to an external source event's
# merged uid, so each occurrence of a recurring source event gets its own
# identity - see _external_uid / _split_occurrence.
OCCURRENCE_SEPARATOR = "::rid::"


def _extract_field_text(item: dict, field: str) -> str:
    if field == "any":
        return " ".join(
            [item.get("summary") or "", item.get("description") or "", item.get("location") or ""]
        )
    return item.get(field) or ""


def _matches_filter(item: dict, rule: dict | None) -> bool:
    """Apply one source's include/exclude rule (keyword or regex) to a raw event dict."""
    if not rule:
        return True

    case_sensitive = rule.get("case_sensitive", False)
    use_regex = rule.get("use_regex", False)
    text = _extract_field_text(item, rule.get("field", "any"))
    text_cmp = text if case_sensitive else text.lower()
    flags = 0 if case_sensitive else re.IGNORECASE

    def _one_matches(pattern_or_word: str) -> bool:
        if use_regex:
            try:
                return re.search(pattern_or_word, text, flags) is not None
            except re.error as err:
                _LOGGER.warning("Ogiltigt regex-mönster %r: %s", pattern_or_word, err)
                return False
        word_cmp = pattern_or_word if case_sensitive else pattern_or_word.lower()
        return word_cmp in text_cmp

    include = rule.get("include") or []
    if include and not any(_one_matches(w) for w in include):
        return False

    exclude = rule.get("exclude") or []
    if any(_one_matches(w) for w in exclude):
        return False

    return True


def _apply_rename(item: dict, rules: list[dict] | None) -> dict:
    """Run a source's ordered list of regex find/replace rules over an event's fields.

    Each rule targets one field (default "summary": title/beskrivning/plats
    are the other options) and rules run in order, each on the previous
    rule's output for that field - so a source can e.g. first strip a
    " // Team Name" suffix a scheduling site always adds, then rename what's
    left ("Träning" -> "Fotbolls Träning") without needing capture groups at
    all - though \\1 etc. in the replacement work too, for when a rule does
    need to keep part of the original text.
    """
    fields = {
        "summary": item.get("summary") or "",
        "description": item.get("description"),
        "location": item.get("location"),
    }
    for rule in rules or []:
        pattern = rule.get("pattern") or ""
        if not pattern:
            continue
        field = rule.get("field") or "summary"
        current = fields.get(field)
        if current is None:
            continue
        try:
            fields[field] = re.sub(pattern, rule.get("replacement", ""), current)
        except re.error as err:
            _LOGGER.warning("Ogiltigt regex-mönster för namnbyte %r: %s", pattern, err)
    return fields


def _events_fingerprint(events: list[CalendarEvent]) -> str:
    """Cheap "did the merged set change" signature, for bumping the CalDAV ctag on a poll."""
    payload = "\n".join(
        f"{e.uid}\0{e.summary}\0{e.start}\0{e.end}\0{e.description}\0{e.location}" for e in events
    )
    return hashlib.sha1(payload.encode()).hexdigest()


def _parse_merged_uid(merged_uid: str) -> tuple[str, str] | None:
    """Split a merged uid back into (source_entity_id, original_uid)."""
    if UID_SEPARATOR not in merged_uid:
        return None
    entity_id, orig_uid = merged_uid.split(UID_SEPARATOR, 1)
    return entity_id, orig_uid


def _resolve_uid(uid: str, action: str) -> tuple[str, str]:
    parsed = _parse_merged_uid(uid)
    if not parsed:
        raise HomeAssistantError(f"Okänt event-id, kan inte {action} eventet")
    return parsed


def _get_source_entity(hass: HomeAssistant, entity_id: str):
    """Get the live source calendar entity object so we can call update/delete on it directly.

    This mirrors how Home Assistant's own calendar websocket API resolves
    entities, since there is no generic `calendar.update_event` /
    `calendar.delete_event` service.
    """
    component = hass.data.get(CALENDAR_DOMAIN)
    if component is None:
        return None
    return component.get_entity(entity_id)


def _external_uid(entity_id: str, orig_uid: str, recurrence_id: str | None) -> str:
    """Merged uid for an event from an external source - unique per occurrence.

    A recurring source event comes back expanded: every occurrence shares the
    source's uid and is told apart only by its recurrence_id. Folding the
    recurrence_id into our uid gives each occurrence its own identity, which
    the ICS feed and CalDAV need (one resource / one UID per flat event - the
    same model the own store already uses, see own_calendar.RECURRENCE_SEPARATOR)
    and which update_event/delete_event unfold again (_split_occurrence) to
    forward the edit to exactly that occurrence in the source.
    """
    base = f"{entity_id}{UID_SEPARATOR}{orig_uid}"
    return f"{base}{OCCURRENCE_SEPARATOR}{recurrence_id}" if recurrence_id else base


def _split_occurrence(orig_uid: str) -> tuple[str, str | None]:
    """Undo the recurrence_id part of _external_uid: (source uid, recurrence_id or None)."""
    if OCCURRENCE_SEPARATOR in orig_uid:
        source_uid, recurrence_id = orig_uid.rsplit(OCCURRENCE_SEPARATOR, 1)
        return source_uid, recurrence_id
    return orig_uid, None


def _parse_event_time(value):
    """Date/datetime from either a live CalendarEvent field or a service-response string."""
    if not isinstance(value, str):
        return value
    # parse_date first: parse_datetime "succeeds" on a pure date string too
    # (as a naive midnight datetime), which breaks all-day events.
    return dt_util.parse_date(value) or dt_util.parse_datetime(value)


async def _fetch_source_items(hass: HomeAssistant, entity_id: str, start, end) -> list[dict]:
    """Raw events from one source, as dicts (summary/description/location/start/end/uid/recurrence_id).

    Asks the source entity directly rather than via the `calendar.get_events`
    service: the service strips everything except start/end/summary/
    description/location (homeassistant/components/calendar/const.py,
    LIST_EVENT_FIELDS) - no uid, no recurrence_id - so every occurrence of a
    recurring source event used to end up with the same summary-based uid,
    which broke forwarding edits/deletes to the source and collapsed series
    to a single event in ICS/CalDAV clients. The service is only a fallback
    for when the entity object can't be resolved.
    """
    entity = _get_source_entity(hass, entity_id)
    if entity is not None:
        source_events = await entity.async_get_events(hass, start, end)
        return [
            {
                "summary": e.summary,
                "description": e.description,
                "location": e.location,
                "start": e.start,
                "end": e.end,
                "uid": e.uid,
                "recurrence_id": e.recurrence_id,
            }
            for e in source_events
        ]

    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": entity_id,
            "start_date_time": start.isoformat(),
            "end_date_time": end.isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    return list(response.get(entity_id, {}).get("events", []))


async def fetch_merged_events(
    hass: HomeAssistant,
    sources: list[str],
    start,
    end,
    filters: dict | None = None,
    renames: dict | None = None,
) -> tuple[list[CalendarEvent], list[str]]:
    """Query every source calendar entity, apply that source's filter, and merge the results.

    Sources are queried concurrently - one slow source (e.g. a remote ICS
    URL) no longer delays all the others.

    Returns (events, failed_entity_ids) so callers can surface source errors.
    """
    filters = filters or {}
    renames = renames or {}
    events: list[CalendarEvent] = []
    failed: list[str] = []

    results = await asyncio.gather(
        *(_fetch_source_items(hass, entity_id, start, end) for entity_id in sources),
        return_exceptions=True,
    )

    for entity_id, items in zip(sources, results):
        if isinstance(items, BaseException):
            _LOGGER.warning("Could not fetch events from %s: %s", entity_id, items)
            failed.append(entity_id)
            continue

        rule = filters.get(entity_id)
        rename_rules = renames.get(entity_id)
        for item in items:
            if not _matches_filter(item, rule):
                continue
            start_val = _parse_event_time(item["start"])
            end_val = _parse_event_time(item["end"])
            # No uid at all (only possible via the service fallback): make it
            # at least unique per occurrence instead of per title.
            orig_uid = item.get("uid") or f"{item.get('summary') or ''}@{start_val}"
            renamed = _apply_rename(item, rename_rules)
            events.append(
                CalendarEvent(
                    start=start_val,
                    end=end_val,
                    summary=renamed["summary"],
                    description=renamed["description"],
                    location=renamed["location"],
                    uid=_external_uid(entity_id, orig_uid, item.get("recurrence_id")),
                )
            )

    events.sort(key=lambda e: str(e.start))
    return events, failed


async def fetch_all_events(
    hass: HomeAssistant, entry: ConfigEntry, store: OwnCalendarStore, start, end
) -> tuple[list[CalendarEvent], list[str]]:
    """Combine this entry's own stored events with its external sources."""
    own_events = [
        CalendarEvent(
            start=e.start,
            end=e.end,
            summary=e.summary,
            description=e.description,
            location=e.location,
            uid=f"{OWN_SOURCE_MARKER}{UID_SEPARATOR}{e.uid}",
        )
        for e in store.events_in_range(start, end)
    ]
    external_events, failed = await fetch_merged_events(
        hass,
        entry.data.get(CONF_SOURCES, []),
        start,
        end,
        entry.data.get(CONF_FILTERS, {}),
        entry.data.get(CONF_RENAME, {}),
    )
    events = sorted(own_events + external_events, key=lambda e: str(e.start))
    return events, failed


async def create_event(hass: HomeAssistant, entry: ConfigEntry, store: OwnCalendarStore, **kwargs) -> CalendarEvent:
    """New events created on a merged calendar are always stored directly (shared by the entity and CalDAV)."""
    event = await store.async_create_event(**kwargs)
    await async_log(hass, entry.entry_id, f"Event skapat: {event.summary}")
    return event


async def update_event(
    hass: HomeAssistant,
    entry: ConfigEntry,
    store: OwnCalendarStore,
    uid: str,
    event: dict,
    recurrence_id: str | None = None,
    recurrence_range: str | None = None,
) -> None:
    """Route an edit to the own store or the owning external source (shared by the entity and CalDAV)."""
    marker, orig_uid = _resolve_uid(uid, action="redigera")
    if marker == OWN_SOURCE_MARKER:
        await store.async_update_event(orig_uid, event, recurrence_id=recurrence_id)
    else:
        source = _get_source_entity(hass, marker)
        if source is None:
            raise HomeAssistantError(f"Källkalendern {marker} hittades inte")
        if not source.supported_features & CalendarEntityFeature.UPDATE_EVENT:
            raise HomeAssistantError(f"Källkalendern {marker} stödjer inte redigering av event")
        source_uid, occurrence_id = _split_occurrence(orig_uid)
        await source.async_update_event(
            source_uid,
            event,
            recurrence_id=recurrence_id or occurrence_id,
            recurrence_range=recurrence_range,
        )
    await async_log(hass, entry.entry_id, f"Event uppdaterat: {event.get('summary') or orig_uid}")


async def delete_event(
    hass: HomeAssistant,
    entry: ConfigEntry,
    store: OwnCalendarStore,
    uid: str,
    recurrence_id: str | None = None,
    recurrence_range: str | None = None,
) -> None:
    """Route a delete to the own store or the owning external source (shared by the entity and CalDAV)."""
    marker, orig_uid = _resolve_uid(uid, action="ta bort")
    if marker == OWN_SOURCE_MARKER:
        await store.async_delete_event(orig_uid, recurrence_id=recurrence_id)
    else:
        source = _get_source_entity(hass, marker)
        if source is None:
            raise HomeAssistantError(f"Källkalendern {marker} hittades inte")
        if not source.supported_features & CalendarEntityFeature.DELETE_EVENT:
            raise HomeAssistantError(f"Källkalendern {marker} stödjer inte borttagning av event")
        source_uid, occurrence_id = _split_occurrence(orig_uid)
        await source.async_delete_event(
            source_uid,
            recurrence_id=recurrence_id or occurrence_id,
            recurrence_range=recurrence_range,
        )
    await async_log(hass, entry.entry_id, f"Event borttaget: {orig_uid}")


def _failed_sources_issue_id(entry: ConfigEntry) -> str:
    return f"failed_sources_{entry.entry_id}"


async def _notify_failed_sources(hass: HomeAssistant, entry: ConfigEntry, failed: list[str]) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        _failed_sources_issue_id(entry),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="failed_sources",
        translation_placeholders={
            "name": entry.data.get(CONF_NAME, "Merged Calendar"),
            "sources": "\n".join(f"- {e}" for e in failed),
        },
    )
    await async_log(hass, entry.entry_id, "Källa svarar inte: " + ", ".join(failed))


async def _dismiss_failed_notification(hass: HomeAssistant, entry: ConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, _failed_sources_issue_id(entry))
    await async_log(hass, entry.entry_id, "Alla källor svarar igen")


def _remove_stale_own_entity(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the leftover separate "(egen)" entity earlier versions created.

    The own calendar's events now live directly on the merged entity, so the
    second entity_registry entry (if any, from before this change) is dead
    weight - remove it so it doesn't linger as "unavailable".
    """
    ent_reg = er.async_get(hass)
    old_entity_id = ent_reg.async_get_entity_id("calendar", DOMAIN, f"{entry.entry_id}_own")
    if old_entity_id:
        ent_reg.async_remove(old_entity_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    _remove_stale_own_entity(hass, entry)

    store = OwnCalendarStore(hass, entry.entry_id)
    await store.async_load()
    hass.data[DOMAIN][entry.entry_id]["own_store"] = store

    coordinator = MergedCalendarCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator
    async_add_entities([MergedCalendarEntity(coordinator, entry, store)])


class MergedCalendarCoordinator(DataUpdateCoordinator):
    """Polls all sources periodically so the entity state stays fresh."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, store: OwnCalendarStore) -> None:
        super().__init__(hass, _LOGGER, name="cal_combiner", update_interval=SCAN_INTERVAL)
        self.entry = entry
        self._store = store
        self._fail_streaks: dict[str, int] = {}
        self._last_notified_failed: set[str] = set()
        self._last_fingerprint: str | None = None

    async def _async_update_data(self):
        now = dt_util.now()
        events, failed = await fetch_all_events(
            self.hass, self.entry, self._store, now - timedelta(days=1), now + timedelta(days=30)
        )

        failed_set = set(failed)
        for source in failed_set:
            self._fail_streaks[source] = self._fail_streaks.get(source, 0) + 1
        for source in list(self._fail_streaks):
            if source not in failed_set:
                del self._fail_streaks[source]

        # Retry/backoff: a source only gets escalated to a user-visible repair
        # issue once it's failed FAILURE_THRESHOLD polls in a row, not on the
        # first blip - see FAILURE_THRESHOLD's docstring. `failed` (below,
        # returned as-is) still reflects the raw, un-debounced per-poll result,
        # since that source's events genuinely are missing from this poll
        # either way.
        persistently_failed = {s for s, count in self._fail_streaks.items() if count >= FAILURE_THRESHOLD}
        if persistently_failed and persistently_failed != self._last_notified_failed:
            await _notify_failed_sources(self.hass, self.entry, sorted(persistently_failed))
        elif not persistently_failed and self._last_notified_failed:
            await _dismiss_failed_notification(self.hass, self.entry)
        self._last_notified_failed = persistently_failed

        # Our own store already bumps the CalDAV ctag on every mutation of its
        # own, but a merged external source calendar changing (an event
        # added/edited/removed there) never touches our store - the only way
        # to notice that here is comparing this poll's merged result against
        # the last one, so CalDAV clients relying on getctag actually re-sync.
        fingerprint = _events_fingerprint(events)
        if self._last_fingerprint is not None and fingerprint != self._last_fingerprint:
            await self._store.async_touch_ctag()
        self._last_fingerprint = fingerprint

        return {"events": events, "failed": failed}


class MergedCalendarEntity(CoordinatorEntity, CalendarEntity):
    """A single calendar entity: shows merged events and owns the events created on it directly."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
    )

    def __init__(self, coordinator: MergedCalendarCoordinator, entry: ConfigEntry, store: OwnCalendarStore) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._store = store
        self._attr_unique_id = entry.entry_id
        self._attr_name = entry.data.get(CONF_NAME, "Merged Calendar")

    @property
    def icon(self) -> str:
        return self._entry.data.get(CONF_ICON) or DEFAULT_MERGE_ICON

    @property
    def entity_picture(self) -> str | None:
        return self._entry.data.get(CONF_PICTURE) or None

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        data = self.coordinator.data or {"events": []}
        upcoming = [e for e in data["events"] if str(e.end) >= str(now)]
        return upcoming[0] if upcoming else None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        failed = data.get("failed") or []
        return {"failed_sources": failed} if failed else {}

    async def async_get_events(self, hass, start_date, end_date) -> list[CalendarEvent]:
        events, _failed = await fetch_all_events(hass, self._entry, self._store, start_date, end_date)
        return events

    async def async_create_event(self, **kwargs) -> None:
        """New events created from the merged calendar are stored directly."""
        await create_event(self.hass, self._entry, self._store, **kwargs)
        await self.coordinator.async_request_refresh()

    async def async_update_event(
        self, uid: str, event: dict, recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        await update_event(
            self.hass, self._entry, self._store, uid, event,
            recurrence_id=recurrence_id, recurrence_range=recurrence_range,
        )
        await self.coordinator.async_request_refresh()

    async def async_delete_event(
        self, uid: str, recurrence_id: str | None = None, recurrence_range: str | None = None
    ) -> None:
        await delete_event(
            self.hass, self._entry, self._store, uid,
            recurrence_id=recurrence_id, recurrence_range=recurrence_range,
        )
        await self.coordinator.async_request_refresh()
