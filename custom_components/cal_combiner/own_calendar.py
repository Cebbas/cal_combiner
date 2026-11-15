"""Persistent storage for the events a merged calendar owns directly.

Rather than forcing the user to first set up a separate Local Calendar
integration to use as a write target, each merged calendar keeps its own small
built-in store (backed by Home Assistant's storage helper) that new events are
written to by default. This used to back a second, separate `calendar.*`
entity, but that just showed up as a confusing duplicate next to the merged
view - the merged calendar entity in `calendar.py` now reads from and writes
to this store directly instead.

Recurring events (an `rrule`) are stored once as a "master" item and expanded
on read. A single occurrence can be addressed by a compound uid of
`f"{master_uid}/{occurrence_start_isoformat}"`, which doubles as both Home
Assistant's `recurrence_id` concept and CalDAV's `RECURRENCE-ID` property -
one storage model serves both call sites without duplicating logic.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any
import uuid

from dateutil.rrule import rrulestr

from homeassistant.components.calendar import CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1
RECURRENCE_SEPARATOR = "/"


def _parse(value: str) -> date | datetime:
    # parse_date must be tried first: parse_datetime happily "succeeds" on a
    # pure date string too (as a naive midnight datetime), which fails
    # CalendarEvent's "all values need a timezone" validation for what should
    # have been an all-day (date-only) event.
    return dt_util.parse_date(value) or dt_util.parse_datetime(value)


def _serialize(value: date | datetime) -> str:
    return value.isoformat()


def _is_all_day(value: date | datetime) -> bool:
    return not isinstance(value, datetime)


def _as_datetime(value: date | datetime) -> datetime:
    """Normalize date/datetime to an aware datetime so rrule math is consistent."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_util.UTC)
    return datetime.combine(value, datetime.min.time(), tzinfo=dt_util.UTC)


def local_tz():
    """Home Assistant's configured zone - the wall clock recurring events repeat in."""
    return dt_util.get_default_time_zone()


def recurrence_start(value: date | datetime) -> date | datetime:
    """A recurring master's start in HA's local zone (dates pass through).

    Stored starts carry only a fixed UTC offset (isoformat), so expanding an
    rrule straight from them repeats at a fixed offset: a weekly 17:00 event
    created in summer (+02:00) would land at 16:00 local after the switch to
    winter time. Expanding from the start in the named local zone keeps the
    wall-clock time and lets each occurrence pick up its own DST offset.
    """
    if not isinstance(value, datetime):
        return value
    return _as_datetime(value).astimezone(local_tz())


def occurrence_key(value: date | datetime) -> str:
    """Canonical key for one occurrence: date isoformat, or its instant in HA's local zone.

    Used for exdates/overrides and the compound occurrence uid. Anything that
    names an occurrence by instant (a CalDAV RECURRENCE-ID in UTC or the
    client's own zone) maps to the same key.
    """
    if not isinstance(value, datetime):
        return value.isoformat()
    return _as_datetime(value).astimezone(local_tz()).isoformat()


def canonical_occ_key(item: dict[str, Any], key: str) -> str:
    """Translate a possibly pre-0.0.22 occurrence key into the current format.

    Older versions expanded at the master's fixed offset, so their keys are
    the occurrence's *wall time* (unchanged by DST) at that offset - e.g.
    "2026-12-01T17:00:00+02:00" for what is really 17:00 local in winter.
    A key already in canonical form is returned as-is; otherwise its wall
    time offset from the master's is re-applied to the master's local start.
    """
    parsed = _parse(key) if key else None
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        return key
    if occurrence_key(parsed) == key:
        return key
    master = _parse(item["start"])
    if not isinstance(master, datetime):
        return key
    master_aware = _as_datetime(master)
    local_master = master_aware.astimezone(local_tz())
    wall = local_master.replace(tzinfo=None) + (parsed.replace(tzinfo=None) - master_aware.replace(tzinfo=None))
    return wall.replace(tzinfo=local_tz()).isoformat()


def _migrate_occ_keys(item: dict[str, Any]) -> bool:
    """Rewrite a recurring item's legacy exdate/override keys in place. True if anything changed."""
    if not item.get("rrule"):
        return False
    changed = False
    exdates = item.get("exdates") or []
    new_exdates = [canonical_occ_key(item, k) for k in exdates]
    if new_exdates != exdates:
        item["exdates"] = new_exdates
        changed = True
    overrides = item.get("overrides") or {}
    new_overrides = {canonical_occ_key(item, k): v for k, v in overrides.items()}
    if list(new_overrides) != list(overrides):
        item["overrides"] = new_overrides
        changed = True
    return changed


class OwnCalendarStore:
    """Persists a merged calendar's own events as plain JSON."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_own_{entry_id}")
        self.events: list[dict[str, Any]] = []
        self.ctag: int = 0

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self.events = (data or {}).get("events", [])
        self.ctag = (data or {}).get("ctag", 0)
        migrated = [_migrate_occ_keys(item) for item in self.events]
        if any(migrated):
            await self._async_save()

    async def async_remove(self) -> None:
        """Delete the underlying storage file entirely (the owning entry is being deleted)."""
        await self._store.async_remove()

    async def async_touch_ctag(self) -> None:
        """Bump ctag with no event change of our own - a merged external source changed instead.

        CalDAV clients use getctag to cheaply tell "did anything in this
        collection change" without re-fetching everything, but our own
        mutations aren't the only thing that can change what the collection
        serves: an external source calendar picking up a new/edited/removed
        event on the coordinator's poll changes it too.
        """
        self.ctag += 1
        await self._store.async_save({"events": self.events, "ctag": self.ctag})

    async def _async_save(self) -> None:
        # Bumped on every mutation so CalDAV clients can cheaply tell "did
        # anything in this collection change" without re-fetching everything.
        self.ctag += 1
        await self._store.async_save({"events": self.events, "ctag": self.ctag})

    def _find(self, uid: str) -> dict[str, Any] | None:
        return next((i for i in self.events if i["uid"] == uid), None)

    def get_master(self, uid: str) -> dict[str, Any] | None:
        """Raw stored item (master fields + rrule/exdates/overrides, not expanded)."""
        return self._find(uid)

    def masters_overlapping(self, start, end) -> list[dict[str, Any]]:
        """Raw stored items (not expanded into occurrences) with at least one occurrence in [start, end]."""
        return [item for item in self.events if self._expand(item, start, end)]

    async def async_put_master(
        self,
        uid: str,
        *,
        summary: str,
        description: str | None,
        location: str | None,
        start: date | datetime,
        end: date | datetime,
        rrule: str | None = None,
        exdates: list[str] | None = None,
        overrides: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Full-resource create-or-replace, matching CalDAV PUT semantics (unlike the
        incremental async_update_event used by Home Assistant's own entity API)."""
        item = self._find(uid)
        if item is None:
            item = {"uid": uid}
            self.events.append(item)
        item["summary"] = summary
        item["description"] = description
        item["location"] = location
        item["start"] = _serialize(start)
        item["end"] = _serialize(end)
        if rrule:
            item["rrule"] = rrule
            item["exdates"] = exdates or []
            item["overrides"] = overrides or {}
        else:
            item.pop("rrule", None)
            item.pop("exdates", None)
            item.pop("overrides", None)
        await self._async_save()

    def _master_event(self, item: dict[str, Any]) -> CalendarEvent:
        return CalendarEvent(
            start=_parse(item["start"]),
            end=_parse(item["end"]),
            summary=item.get("summary", ""),
            description=item.get("description"),
            location=item.get("location"),
            uid=item["uid"],
        )

    def _expand(self, item: dict[str, Any], start, end) -> list[CalendarEvent]:
        """Expand one stored item (master or recurring) into occurrences overlapping [start, end]."""
        rrule = item.get("rrule")
        master_start = _parse(item["start"])
        master_end = _parse(item["end"])

        if not rrule:
            if str(master_end) >= str(start) and str(master_start) <= str(end):
                return [self._master_event(item)]
            return []

        all_day = _is_all_day(master_start)
        duration = _as_datetime(master_end) - _as_datetime(master_start)
        # All-day: UTC midnight as before (only the date matters). Timed:
        # repeat in HA's local zone so DST doesn't shift the wall-clock time.
        dtstart = _as_datetime(master_start) if all_day else recurrence_start(master_start)

        try:
            rule = rrulestr(rrule, dtstart=dtstart)
            occurrences = rule.between(
                _as_datetime(start) - duration, _as_datetime(end), inc=True
            )
        except (ValueError, TypeError) as err:
            _LOGGER.warning("Ogiltig RRULE %r för event %s: %s", rrule, item["uid"], err)
            return [self._master_event(item)] if str(master_end) >= str(start) and str(master_start) <= str(end) else []

        exdates = set(item.get("exdates") or [])
        overrides = item.get("overrides") or {}
        results: list[CalendarEvent] = []

        for occ in occurrences:
            occ_key_dt = occ.replace(tzinfo=dt_util.UTC) if occ.tzinfo is None else occ
            occ_start = occ_key_dt.date() if all_day else occ_key_dt
            occ_key = occurrence_key(occ_start)
            if occ_key in exdates:
                continue

            override = overrides.get(occ_key)
            if override:
                occ_start_final = _parse(override["start"]) if "start" in override else occ_start
                occ_end_final = (
                    _parse(override["end"]) if "end" in override else occ_start_final + duration
                )
                summary = override.get("summary", item.get("summary", ""))
                description = override.get("description", item.get("description"))
                location = override.get("location", item.get("location"))
            else:
                occ_start_final = occ_start
                occ_end_final = occ_start + duration
                summary = item.get("summary", "")
                description = item.get("description")
                location = item.get("location")

            if not (str(occ_end_final) >= str(start) and str(occ_start_final) <= str(end)):
                continue

            results.append(
                CalendarEvent(
                    start=occ_start_final,
                    end=occ_end_final,
                    summary=summary,
                    description=description,
                    location=location,
                    uid=f"{item['uid']}{RECURRENCE_SEPARATOR}{occ_key}",
                )
            )

        return results

    def events_in_range(self, start, end) -> list[CalendarEvent]:
        result: list[CalendarEvent] = []
        for item in self.events:
            result.extend(self._expand(item, start, end))
        result.sort(key=lambda e: str(e.start))
        return result

    def upcoming(self, now) -> CalendarEvent | None:
        far_future = now + timedelta(days=3650)
        upcoming = [e for e in self.events_in_range(now, far_future) if str(e.end) >= str(now)]
        upcoming.sort(key=lambda e: str(e.start))
        return upcoming[0] if upcoming else None

    async def async_create_event(self, **kwargs: Any) -> CalendarEvent:
        item = {
            "uid": kwargs.get("uid") or str(uuid.uuid4()),
            "summary": kwargs.get("summary", ""),
            "description": kwargs.get("description"),
            "location": kwargs.get("location"),
            "start": _serialize(kwargs["dtstart"]),
            "end": _serialize(kwargs["dtend"]),
        }
        rrule = kwargs.get("rrule")
        if rrule:
            item["rrule"] = rrule
            item["exdates"] = []
            item["overrides"] = {}
        self.events.append(item)
        await self._async_save()
        return self._master_event(item)

    @staticmethod
    def _split_recurrence_uid(uid: str) -> tuple[str, str | None]:
        if RECURRENCE_SEPARATOR in uid:
            master_uid, occ_key = uid.split(RECURRENCE_SEPARATOR, 1)
            return master_uid, occ_key
        return uid, None

    async def async_update_event(
        self, uid: str, event: dict[str, Any], recurrence_id: str | None = None
    ) -> None:
        master_uid, occ_key = self._split_recurrence_uid(uid)
        item = self._find(master_uid)
        if item is None:
            raise KeyError(uid)

        # Editing one occurrence of a recurring series (either addressed via the
        # compound uid directly, or via the recurrence_id HA passes separately).
        target_occ_key = occ_key or recurrence_id
        if item.get("rrule") and target_occ_key:
            target_occ_key = canonical_occ_key(item, target_occ_key)
            override: dict[str, Any] = {}
            if "summary" in event:
                override["summary"] = event["summary"]
            if "description" in event:
                override["description"] = event["description"]
            if "location" in event:
                override["location"] = event["location"]
            if "dtstart" in event:
                override["start"] = _serialize(event["dtstart"])
            if "dtend" in event:
                override["end"] = _serialize(event["dtend"])
            item.setdefault("overrides", {})[target_occ_key] = override
            await self._async_save()
            return

        # Whole series (or a plain, non-recurring event).
        item["summary"] = event.get("summary", item.get("summary", ""))
        item["description"] = event.get("description", item.get("description"))
        item["location"] = event.get("location", item.get("location"))
        if "dtstart" in event:
            item["start"] = _serialize(event["dtstart"])
        if "dtend" in event:
            item["end"] = _serialize(event["dtend"])
        # rrule is only touched when the caller actually sends the key -
        # every other edit (title/time/location on an already-recurring
        # master) must leave its existing rrule/exdates/overrides alone.
        # A truthy rrule here turns a plain event into a recurring one (or
        # changes an existing series' rule) without discarding exdates/
        # overrides already made under the old rule; an explicit falsy
        # rrule clears recurrence entirely, mirroring async_put_master.
        if "rrule" in event:
            rrule = event["rrule"]
            if rrule:
                item["rrule"] = rrule
                item.setdefault("exdates", [])
                item.setdefault("overrides", {})
            else:
                item.pop("rrule", None)
                item.pop("exdates", None)
                item.pop("overrides", None)
        await self._async_save()

    async def async_delete_event(self, uid: str, recurrence_id: str | None = None) -> None:
        master_uid, occ_key = self._split_recurrence_uid(uid)
        target_occ_key = occ_key or recurrence_id

        item = self._find(master_uid)
        if item is None:
            raise KeyError(uid)

        if item.get("rrule") and target_occ_key:
            target_occ_key = canonical_occ_key(item, target_occ_key)
            item.setdefault("exdates", []).append(target_occ_key)
            item.get("overrides", {}).pop(target_occ_key, None)
            await self._async_save()
            return

        before = len(self.events)
        self.events = [i for i in self.events if i["uid"] != master_uid]
        if len(self.events) == before:
            raise KeyError(uid)
        await self._async_save()
