"""Calendar platform for Cal Combiner."""
from __future__ import annotations

from datetime import timedelta
import logging
import re

from homeassistant.components import persistent_notification
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
UID_SEPARATOR = "::"
# Marks a merged uid as belonging to the calendar's own store rather than an
# external source entity_id (which can never collide with this, since entity
# ids always contain a domain and a dot, e.g. "calendar.foo").
OWN_SOURCE_MARKER = "__own__"


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


async def fetch_merged_events(
    hass: HomeAssistant,
    sources: list[str],
    start,
    end,
    filters: dict | None = None,
    renames: dict | None = None,
) -> tuple[list[CalendarEvent], list[str]]:
    """Query every source calendar entity, apply that source's filter, and merge the results.

    Returns (events, failed_entity_ids) so callers can surface source errors.
    """
    filters = filters or {}
    renames = renames or {}
    events: list[CalendarEvent] = []
    failed: list[str] = []

    for entity_id in sources:
        try:
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
        except Exception as err:  # noqa: BLE001 - keep merging even if one source fails
            _LOGGER.warning("Could not fetch events from %s: %s", entity_id, err)
            failed.append(entity_id)
            continue

        rule = filters.get(entity_id)
        rename_rules = renames.get(entity_id)
        for item in response.get(entity_id, {}).get("events", []):
            if not _matches_filter(item, rule):
                continue
            # parse_date first: parse_datetime "succeeds" on a pure date string too
            # (as a naive midnight datetime), which breaks all-day events.
            start_val = dt_util.parse_date(item["start"]) or dt_util.parse_datetime(item["start"])
            end_val = dt_util.parse_date(item["end"]) or dt_util.parse_datetime(item["end"])
            orig_uid = item.get("uid") or item.get("summary") or ""
            renamed = _apply_rename(item, rename_rules)
            events.append(
                CalendarEvent(
                    start=start_val,
                    end=end_val,
                    summary=renamed["summary"],
                    description=renamed["description"],
                    location=renamed["location"],
                    uid=f"{entity_id}{UID_SEPARATOR}{orig_uid}",
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
        await source.async_update_event(
            orig_uid, event, recurrence_id=recurrence_id, recurrence_range=recurrence_range
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
        await source.async_delete_event(
            orig_uid, recurrence_id=recurrence_id, recurrence_range=recurrence_range
        )
    await async_log(hass, entry.entry_id, f"Event borttaget: {orig_uid}")


async def _notify_failed_sources(hass: HomeAssistant, entry: ConfigEntry, failed: list[str]) -> None:
    persistent_notification.async_create(
        hass,
        (
            f"Följande källkalendrar svarade inte och är tillfälligt uteslutna ur "
            f"\"{entry.data.get(CONF_NAME, 'Merged Calendar')}\":\n\n"
            + "\n".join(f"- {e}" for e in failed)
        ),
        title="Cal Combiner: en källa svarar inte",
        notification_id=f"cal_combiner_failed_{entry.entry_id}",
    )
    await async_log(hass, entry.entry_id, "Källa svarar inte: " + ", ".join(failed))


async def _dismiss_failed_notification(hass: HomeAssistant, entry: ConfigEntry) -> None:
    persistent_notification.async_dismiss(hass, f"cal_combiner_failed_{entry.entry_id}")
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
        self._last_failed: set[str] = set()

    async def _async_update_data(self):
        now = dt_util.now()
        events, failed = await fetch_all_events(
            self.hass, self.entry, self._store, now - timedelta(days=1), now + timedelta(days=30)
        )

        failed_set = set(failed)
        if failed_set and failed_set != self._last_failed:
            await _notify_failed_sources(self.hass, self.entry, failed)
        elif not failed_set and self._last_failed:
            await _dismiss_failed_notification(self.hass, self.entry)
        self._last_failed = failed_set

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
