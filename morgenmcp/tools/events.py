"""MCP tools for Morgen event operations."""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import MISSING

from morgenmcp.client import MorgenClient, get_client
from morgenmcp.models import (
    Event,
    EventCreateRequest,
    EventDeleteRequest,
    EventUpdateRequest,
    MorgenAPIError,
)
from morgenmcp.tools.id_registry import register_id
from morgenmcp.tools.id_utils import (
    extract_account_from_calendar,
    extract_ids_from_event,
)
from morgenmcp.tools.outputs import (
    BatchDeleteEventsResult,
    BatchUpdateResult,
    CreateEventResult,
    DeleteEventResult,
    EventAlert,
    EventItem,
    EventLocation,
    EventParticipant,
    EventRecurrenceRule,
    FailedItem,
    ListEventsResult,
    MutateEventResult,
)
from morgenmcp.tools.utils import (
    build_alerts_dict,
    build_locations_dict,
    build_participants_dict,
    build_recurrence_rules,
    calendar_not_found,
    disable_response_caching,
    gather_bounded,
    handle_tool_errors,
    is_not_found,
    omit_none,
    resolve_virtual_id,
    resolve_virtual_ids,
)
from morgenmcp.validators import (
    SUFFIXLESS_DATETIME_PATTERN,
    resolve_event_window,
    validate_duration,
    validate_email,
    validate_google_color_id,
    validate_local_datetime,
    validate_timezone,
)

_DISPLAY_TZ_ENV = "MORGENMCP_DISPLAY_TZ"
_UTC_TZ_NAMES = frozenset({"UTC", "Etc/UTC", "Etc/GMT", "GMT"})


# events.mdx ("Deleted and unknown events"): a 404 from the events API is
# authoritative absence. Rate limits (429), provider outages (5xx), and
# authorization or plan errors (401/403) retain their own status codes.
_EVENT_GONE = (
    "Event with ID '{id}' no longer exists (deleted, cancelled, or not "
    "retrievable from the calendar provider). Re-list events to refresh IDs."
)
_EVENT_ALREADY_GONE_MESSAGE = (
    "Event was already gone (deleted, cancelled, or not retrievable from the "
    "calendar provider). Nothing was removed."
)
# A 404 on the anchor occurrence says nothing about the rest of the series:
# events.mdx says delete reads the target first, so a cancelled occurrence
# 404s while its siblings survive. Only "single" may treat 404 as success.
_SERIES_ANCHOR_GONE = (
    "Event with ID '{id}' no longer exists, so the '{mode}' series delete was "
    "not applied and other occurrences may remain. Re-list events and retry "
    "with {retry_from}."
)
# "future" deletes from the supplied occurrence onward, so retrying from an
# earlier occurrence would widen the scope; "all" can use any occurrence.
_SERIES_RETRY_FROM = {
    "future": (
        "the first surviving occurrence of the same series at or after the "
        "original one (an earlier occurrence would delete more than requested)"
    ),
    "all": "any surviving occurrence of the same series",
}


def _delete_not_found_error(
    event_id: str, series_update_mode: Literal["single", "future", "all"]
) -> str | None:
    """Error text for a delete 404, or None when the 404 means success."""
    if series_update_mode == "single":
        return None
    return _SERIES_ANCHOR_GONE.format(
        id=event_id,
        mode=series_update_mode,
        retry_from=_SERIES_RETRY_FROM[series_update_mode],
    )


def _resolve_event_id(event_id: str) -> str:
    """Validate and resolve a virtual event ID to its real Morgen ID."""
    return resolve_virtual_id(
        event_id,
        parameter="event_id",
        not_found=f"Event with ID '{event_id}' not found. Call list_events first.",
    )


def _resolve_calendar_id(calendar_id: str) -> str:
    """Validate and resolve a virtual calendar ID to its real Morgen ID."""
    return resolve_virtual_id(
        calendar_id,
        parameter="calendar_id",
        not_found=calendar_not_found(calendar_id),
    )


def _validate_event_update_fields(
    *,
    start: str | None,
    duration: str | None,
    time_zone: str | None,
    is_all_day: bool | None,
    alerts: Any,
    use_default_alerts: bool | None,
    google_color_id: str | None,
) -> None:
    """Input checks shared by ``update_event`` and ``batch_update_events``."""
    timing_provided = [
        f for f in (start, duration, time_zone, is_all_day) if f is not None
    ]
    if timing_provided and len(timing_provided) != 4:
        raise ToolError(
            "When updating timing fields (start, duration, time_zone, is_all_day), "
            "all four must be provided together."
        )
    if start is not None:
        validate_local_datetime(start, "start")
    if duration is not None:
        validate_duration(duration)
    if time_zone is not None:
        validate_timezone(time_zone)
    if alerts and use_default_alerts:
        raise ToolError(
            "alerts and use_default_alerts are mutually exclusive — pick one."
        )
    if google_color_id is not None:
        validate_google_color_id(google_color_id)


def _system_localtime(dt: datetime) -> datetime:
    """Resolve an aware or naive datetime against the host OS local timezone."""
    return dt.astimezone()


class _SystemLocalTz(tzinfo):
    """Dynamic tzinfo delegating each boundary/instant to OS local TZ rules."""

    @staticmethod
    def _at(dt: datetime | None) -> datetime:
        if dt is None:
            return _system_localtime(datetime.now(UTC))
        return _system_localtime(dt.replace(tzinfo=None))

    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return self._at(dt).utcoffset()

    def dst(self, dt: datetime | None) -> timedelta | None:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str | None:
        return self._at(dt).tzname()

    def fromutc(self, dt: datetime) -> datetime:
        local = _system_localtime(dt.replace(tzinfo=UTC))
        naive = local.replace(tzinfo=None)
        fold = (
            1
            if _system_localtime(naive.replace(fold=0)).utcoffset() != local.utcoffset()
            else 0
        )
        return naive.replace(fold=fold, tzinfo=self)


_SYSTEM_LOCAL_TZ = _SystemLocalTz()


def _resolve_display_tz(explicit: str | None) -> tzinfo:
    """Pick the display tz: explicit arg > MORGENMCP_DISPLAY_TZ > system local."""
    if explicit:
        return ZoneInfo(explicit)
    env_value = os.environ.get(_DISPLAY_TZ_ENV)
    if env_value:
        try:
            return ZoneInfo(env_value)
        except Exception:
            pass  # bad env var → silently fall through to system tz
    return _SYSTEM_LOCAL_TZ


def _tz_label(dt: datetime, tz: tzinfo) -> str:
    """Render '<abbrev> (<IANA>)' or just '<label>' on fixed-offset/local fallbacks."""
    iana = getattr(tz, "key", None) or dt.tzname() or str(tz)
    abbrev = dt.tzname() or iana
    if abbrev == iana:
        return iana
    return f"{abbrev} ({iana})"


def _classify_event(event: Event) -> str:
    """Return a ``" kind"`` suffix rendered INSIDE the ID brackets, or ``""``.

    The caller emits ``[{virtual_id}{kind}]``, e.g. ``[aB-9xZ_ task,free]``.

    Ordinary busy events get no tag: they are the large majority of any listing,
    and compact output exists to save tokens. A tag marks an item the client
    should *not* treat as a hard commitment.

    ``task`` and ``routine`` are mutually exclusive upstream: creating an event
    with both ``canBeCompleted`` and a ``taskId`` is rejected with HTTP 400,
    "An event with canBeCompleted cannot have a taskId" (reproduced against the
    live API 2026-09-11). The fallthrough order therefore matches the API's own
    constraint, and the ``elif`` chain is a belt-and-braces tiebreak rather than
    a case Morgen can actually produce. A "routine" is Morgen's recurring
    check-off-able block (https://www.morgen.so/routines), displayed like a task
    but carrying no task ID. ``flexible`` marks a Morgen auto-scheduled block,
    which can be moved.

    Completing a routine does NOT clear the tag: a checked-off routine keeps
    ``canBeCompleted=True`` and sets ``progress="completed"`` (verified live).
    The tag says what the item is; ``progress`` says whether it is done.

    No space after the comma, so the bracket content stays two tokens at most.
    """
    meta = event.metadata
    parts: list[str] = []
    if meta and meta.task_id:
        parts.append("task")
    elif meta and meta.can_be_completed:
        parts.append("routine")
    elif meta and meta.is_auto_scheduled:
        parts.append("flexible")
    if event.free_busy_status == "free":
        parts.append("free")
    return f" {','.join(parts)}" if parts else ""


def _format_compact_event(event: Event, display_tz: tzinfo) -> str:
    """Format an event as a compact one-liner: ``"Jul 15 09:15-10:00 CDT (America/Chicago): Title [id]"``.

    Every line includes a ``MMM DD`` date prefix so multi-day listings remain
    scannable. Times are converted from the event's `time_zone` into
    `display_tz` and tagged with the abbreviation plus IANA name. Floating
    events (no source timezone) are tagged "(floating)" and not converted.
    All-day events use ``"MMM DD (all-day)"`` form.

    A kind tag may appear INSIDE the ID brackets (see ``_classify_event``):
    ``[id task]``, ``routine``, ``flexible``, ``free``, or a pair such as
    ``[id task,free]``. An untagged line is an ordinary busy commitment -- the
    common case, left untagged to keep compact output cheap.

    Parsing note: match the trailing ``[<7-char id>( <tag>)?]`` anchored at end
    of line. The tag lives inside the brackets so that a title cannot spoof it:
    with the tag outside, a title ending in ``{free}`` on a busy event rendered
    byte-identically to a genuinely free event, which would lead a client to
    schedule over a hard conflict.
    """
    virtual_id = register_id(event.id)
    title = event.title or "(No title)"
    kind = _classify_event(event)

    if event.show_without_time:
        # All-day event: "Jul 15 (all-day): Holiday [abc123]"
        try:
            dt = datetime.fromisoformat(event.start)
            date_str = dt.strftime("%b %d")
        except (ValueError, TypeError):
            date_str = event.start
        return f"{date_str} (all-day): {title} [{virtual_id}{kind}]"

    try:
        start_naive = datetime.fromisoformat(event.start)

        duration = event.duration or "PT0M"
        hours = 0
        minutes = 0
        if "H" in duration:
            h_part = duration.split("H")[0].replace("PT", "")
            hours = int(h_part) if h_part else 0
            remaining = duration.split("H")[1]
        else:
            remaining = duration.replace("PT", "")
        if "M" in remaining:
            m_part = remaining.replace("M", "")
            minutes = int(m_part) if m_part else 0
        end_naive = start_naive + timedelta(hours=hours, minutes=minutes)

        if event.time_zone is None:
            date_prefix = start_naive.strftime("%b %d")
            start_str = start_naive.strftime("%H:%M")
            end_str = end_naive.strftime("%H:%M")
            cross = end_naive.date() != start_naive.date()
            end_label = f"{end_naive.strftime('%b %d')} {end_str}" if cross else end_str
            return (
                f"{date_prefix} {start_str}-{end_label} (floating): "
                f"{title} [{virtual_id}{kind}]"
            )

        try:
            source_tz = ZoneInfo(event.time_zone)
        except Exception:
            return f"{event.start} {event.time_zone}: {title} [{virtual_id}{kind}]"

        start_dt = start_naive.replace(tzinfo=source_tz).astimezone(display_tz)
        end_dt = end_naive.replace(tzinfo=source_tz).astimezone(display_tz)

        date_prefix = start_dt.strftime("%b %d")
        start_str = start_dt.strftime("%H:%M")
        end_str = end_dt.strftime("%H:%M")
        cross = end_dt.date() != start_dt.date()
        end_label = f"{end_dt.strftime('%b %d')} {end_str}" if cross else end_str
        return (
            f"{date_prefix} {start_str}-{end_label} {_tz_label(start_dt, display_tz)}: "
            f"{title} [{virtual_id}{kind}]"
        )
    except (ValueError, TypeError):
        return f"{event.start}: {title} [{virtual_id}{kind}]"


def _format_full_event(event: Event) -> EventItem:
    """Project a Morgen event onto the MCP output model."""
    metadata = event.metadata
    room = event.derived.virtual_room if event.derived else None
    return EventItem(
        id=register_id(event.id),
        calendarId=register_id(event.calendar_id),
        accountId=register_id(event.account_id),
        title=omit_none(event.title),
        description=omit_none(event.description),
        start=omit_none(event.start),
        duration=omit_none(event.duration),
        timeZone=omit_none(event.time_zone),
        isAllDay=omit_none(event.show_without_time),
        status=omit_none(event.free_busy_status),
        privacy=omit_none(event.privacy),
        locations=[
            EventLocation(name=omit_none(location.name))
            for location in (event.locations or {}).values()
        ]
        or MISSING,
        participants=[
            EventParticipant(
                name=omit_none(participant.name),
                email=omit_none(participant.email),
                status=participant.participation_status,
                isOrganizer=participant.roles.owner if participant.roles else False,
            )
            for participant in (event.participants or {}).values()
        ]
        or MISSING,
        isRecurring=event.recurrence_rules is not None,
        recurrenceRules=[
            EventRecurrenceRule(
                frequency=rule.frequency,
                interval=rule.interval,
                byDay=[day.day for day in (rule.by_day or [])] or MISSING,
            )
            for rule in (event.recurrence_rules or [])
        ]
        or MISSING,
        recurrenceId=omit_none(event.recurrence_id),
        masterEventId=register_id(event.master_event_id)
        if event.master_event_id
        else MISSING,
        alerts=[
            EventAlert(offset=alert.trigger.offset, action=alert.action)
            for alert in (event.alerts or {}).values()
        ]
        or MISSING,
        useDefaultAlerts=event.use_default_alerts or MISSING,
        googleColorId=omit_none(event.google_color_id),
        categoryId=omit_none(metadata.category_id) if metadata else MISSING,
        categoryName=omit_none(metadata.category_name) if metadata else MISSING,
        categoryColor=omit_none(metadata.category_color) if metadata else MISSING,
        taskId=register_id(metadata.task_id)
        if metadata and metadata.task_id
        else MISSING,
        progress=omit_none(metadata.progress) if metadata else MISSING,
        canBeCompleted=omit_none(metadata.can_be_completed) if metadata else MISSING,
        isAutoScheduled=omit_none(metadata.is_auto_scheduled) if metadata else MISSING,
        virtualRoomUrl=omit_none(room.url) if room else MISSING,
    )


@dataclass(frozen=True)
class EventQueryResult:
    """Result of querying events across one or more calendar accounts."""

    events: list[Event]
    account_failures: list[tuple[str, BaseException]]
    account_count: int

    @property
    def is_partial(self) -> bool:
        return bool(self.account_failures)

    @property
    def all_failed(self) -> bool:
        return (
            self.account_count > 0 and len(self.account_failures) == self.account_count
        )


async def query_events(
    client: MorgenClient,
    start: str,
    end: str,
    real_calendar_ids: Sequence[str] | None = None,
    *,
    on_account_done: Callable[[int, int], Awaitable[None]] | None = None,
) -> EventQueryResult:
    """Group calendars by account and fetch events in bounded parallel."""
    calendars_by_account: dict[str, list[str]] = defaultdict(list)
    if real_calendar_ids is not None:
        if not real_calendar_ids:
            return EventQueryResult(events=[], account_failures=[], account_count=0)
        for cal_id in real_calendar_ids:
            calendars_by_account[extract_account_from_calendar(cal_id)].append(cal_id)
    else:
        calendars = await client.list_calendars()
        for cal in calendars:
            calendars_by_account[cal.account_id].append(cal.id)

    account_items = list(calendars_by_account.items())
    if not account_items:
        return EventQueryResult(events=[], account_failures=[], account_count=0)

    async def fetch_account_events(acc_id: str, cal_ids: list[str]) -> list[Event]:
        return await client.list_events(
            account_id=acc_id,
            calendar_ids=cal_ids,
            start=start,
            end=end,
        )

    results = await gather_bounded(
        fetch_account_events(acc_id, cal_ids) for acc_id, cal_ids in account_items
    )

    events: list[Event] = []
    failures: list[tuple[str, BaseException]] = []
    total = len(account_items)
    for i, ((acc_id, _), result) in enumerate(zip(account_items, results, strict=True)):
        if on_account_done is not None:
            await on_account_done(i + 1, total)
        if isinstance(result, BaseException):
            failures.append((acc_id, result))
        else:
            events.extend(result)

    return EventQueryResult(
        events=events,
        account_failures=failures,
        account_count=total,
    )


@handle_tool_errors
async def list_events(
    start: str,
    end: str,
    calendar_ids: list[str] | None = None,
    compact: bool = False,
    display_timezone: str | None = None,
    time_zone: str | None = None,
    ctx: Context | None = None,
) -> ListEventsResult:
    """List events from calendars within a time window.

    Recurring events are automatically expanded to individual occurrences.
    Deleted or cancelled events are not included.

    Args:
        start: Start of the time window in ISO 8601 format, either with an
            explicit offset or ``Z`` (e.g., "2023-03-01T00:00:00-06:00" or
            "2023-03-01T06:00:00Z"), or bare YYYY-MM-DDTHH:mm:ss interpreted
            in ``time_zone`` (defaulting to UTC when ``time_zone`` is omitted).
        end: End of the time window in ISO 8601 format (explicit offset / ``Z``,
            or bare YYYY-MM-DDTHH:mm:ss interpreted in ``time_zone`` / UTC).
            Max 6 months from start.
        calendar_ids: Optional list of virtual calendar IDs. If omitted, queries all calendars.
        compact: If True, returns compact one-liner format to reduce tokens.
            Format: "Jul 15 09:15-10:00 CDT (America/Chicago): Meeting [event_id]"
            A kind tag may appear inside the ID brackets, e.g.
            "[abc123 task]": task (linked to a Morgen task), routine (a
            check-off-able Morgen Routine), flexible (Morgen auto-scheduled, so
            movable), free (does not mark you busy), or a pair like
            "[abc123 task,free]". No tag means an ordinary busy commitment.
            Only task/routine/flexible are mutually exclusive.
        display_timezone: Optional IANA timezone (e.g. "America/Chicago") used to
            render compact times. Defaults to ``time_zone`` if provided, then the
            MORGENMCP_DISPLAY_TZ env var, or the system local timezone if unset.
            Applies only to compact output; floating events are tagged "(floating)".
        time_zone: Optional IANA timezone (e.g. "America/Chicago") used to
            interpret bare ``start``/``end`` window bounds before converting to UTC.
            Do not combine with a ``Z`` or numeric offset on ``start``/``end``.

    Returns:
        Dictionary with 'events' key containing list of event objects (or strings if compact).
    """
    utc_start, utc_end = resolve_event_window(start, end, time_zone=time_zone)
    validate_timezone(display_timezone)

    configured_display_tz = display_timezone or os.environ.get(_DISPLAY_TZ_ENV)
    if (
        ctx
        and time_zone is None
        and configured_display_tz
        and configured_display_tz not in _UTC_TZ_NAMES
        and SUFFIXLESS_DATETIME_PATTERN.match(start)
    ):
        await ctx.warning(
            f"Bare 'start'/'end' bounds without 'time_zone' or an offset are "
            f"interpreted as UTC even when display_timezone={configured_display_tz!r}. "
            f"Pass offsets/Z or time_zone={configured_display_tz!r} if you intended local time."
        )

    client = get_client()
    real_calendar_ids: list[str] | None = None
    if calendar_ids is not None:
        if not calendar_ids:
            raise ToolError("calendar_ids cannot be empty when provided")
        real_calendar_ids = resolve_virtual_ids(
            calendar_ids, parameter="calendar_id", not_found=calendar_not_found
        )

    async def _report_progress(done: int, total: int) -> None:
        if ctx is not None:
            await ctx.report_progress(done, total)

    query = await query_events(
        client,
        utc_start,
        utc_end,
        real_calendar_ids=real_calendar_ids,
        on_account_done=_report_progress if ctx is not None else None,
    )

    if query.all_failed:
        if len(query.account_failures) == 1:
            raise query.account_failures[0][1]
        details = "; ".join(
            f"{register_id(acc_id)}: {err}" for acc_id, err in query.account_failures
        )
        raise ToolError(f"Failed to fetch events for all accounts: {details}")

    if query.is_partial:
        disable_response_caching()
        if ctx is not None:
            for acc_id, err in query.account_failures:
                # register_id: surface the virtual ID, never a raw Morgen ID
                await ctx.warning(
                    f"Failed to fetch events for account {register_id(acc_id)}: {err}"
                )

    all_events = query.events

    # Degraded listings carry the fact in the payload, not only in warnings:
    # log delivery is per-request opt-in on the modern protocol, so a caller
    # that did not stamp _meta.logLevel would otherwise see a complete-looking
    # result with a whole calendar silently missing. Virtual IDs only.
    if compact:
        effective_display_tz = (
            display_timezone if display_timezone is not None else time_zone
        )
        display_tz = _resolve_display_tz(effective_display_tz)
        formatted: list[EventItem] | list[str] = [
            _format_compact_event(event, display_tz) for event in all_events
        ]
    else:
        formatted = [_format_full_event(event) for event in all_events]

    return ListEventsResult(
        events=formatted,
        count=len(all_events),
        partial=True if query.is_partial else MISSING,
        failed_accounts=(
            [register_id(acc_id) for acc_id, _ in query.account_failures]
            if query.is_partial
            else MISSING
        ),
    )


@handle_tool_errors
async def create_event(
    calendar_id: str,
    title: str,
    start: str,
    duration: str,
    time_zone: str | None = None,
    is_all_day: bool = False,
    description: str | None = None,
    location: str | None = None,
    participants: list[str] | None = None,
    free_busy_status: Literal["free", "busy"] = "busy",
    privacy: Literal["public", "private", "secret"] = "public",
    request_virtual_room: Literal["default", "googleMeet", "microsoftTeams"]
    | None = None,
    recurrence_rules: list[dict[str, Any]] | None = None,
    alerts: list[str] | None = None,
    use_default_alerts: bool | None = None,
    google_color_id: str | None = None,
) -> CreateEventResult:
    """Create a new calendar event.

    Args:
        calendar_id: The virtual ID of the calendar to create the event in.
        title: The event title/summary.
        start: Start time in LocalDateTime format (e.g., "2023-03-01T10:15:00").
        duration: Duration in ISO 8601 format (e.g., "PT1H" for 1 hour, "PT30M" for 30 min).
        time_zone: IANA timezone (e.g., "Europe/Berlin"). Use None for floating events.
        is_all_day: True for all-day events, False for timed events.
        description: Optional event description.
        location: Optional location name.
        participants: Optional list of participant email addresses to invite.
        free_busy_status: "free" or "busy" (default: "busy").
        privacy: "public", "private", or "secret" (default: "public").
        request_virtual_room: Request automatic video room creation.
        recurrence_rules: Optional list of recurrence dicts. Each dict needs
            'frequency' (daily|weekly|monthly|yearly), optional 'interval' (default 1),
            optional 'by_day' (list of two-letter codes: mo, tu, we, th, fr, sa, su).
            Example: [{"frequency": "weekly", "interval": 1, "by_day": ["mo", "we"]}].
        alerts: Optional list of negative ISO 8601 offsets (e.g., ['-PT15M', '-PT1H'])
            for reminders before the event. Cannot be combined with use_default_alerts.
        use_default_alerts: If True, use the calendar's default alert settings
            instead of custom alerts. Cannot be combined with alerts.
        google_color_id: Google Calendar color ID, "1" through "11"
            (Google Calendar events only).

    Returns:
        Dictionary with created event ID and details.
    """
    real_calendar_id = _resolve_calendar_id(calendar_id)

    if not title or not title.strip():
        raise ToolError("title cannot be empty")

    validate_local_datetime(start, "start")
    validate_duration(duration)
    validate_timezone(time_zone)

    if participants:
        for email in participants:
            validate_email(email)

    if alerts and use_default_alerts:
        raise ToolError(
            "alerts and use_default_alerts are mutually exclusive — pick one."
        )

    if google_color_id is not None:
        validate_google_color_id(google_color_id)

    real_account_id = extract_account_from_calendar(real_calendar_id)

    request = EventCreateRequest(
        account_id=real_account_id,
        calendar_id=real_calendar_id,
        title=title,
        start=start,
        duration=duration,
        time_zone=time_zone,
        show_without_time=is_all_day,
        description=description,
        locations=build_locations_dict(location),
        participants=build_participants_dict(participants),
        alerts=build_alerts_dict(alerts),
        use_default_alerts=use_default_alerts,
        free_busy_status=free_busy_status,
        privacy=privacy,
        recurrence_rules=build_recurrence_rules(recurrence_rules),
        google_color_id=google_color_id,
        request_virtual_room=request_virtual_room,
    )

    client = get_client()
    response = await client.create_event(request)

    # Register and return virtual IDs
    return {
        "success": True,
        "message": "Event created successfully.",
        "event": {
            "id": register_id(response.event.id),
            "calendarId": register_id(response.event.calendar_id),
            "accountId": register_id(response.event.account_id),
        },
    }


@handle_tool_errors
async def update_event(
    event_id: str,
    title: str | None = None,
    start: str | None = None,
    duration: str | None = None,
    time_zone: str | None = None,
    is_all_day: bool | None = None,
    description: str | None = None,
    location: str | None = None,
    free_busy_status: Literal["free", "busy"] | None = None,
    privacy: Literal["public", "private", "secret"] | None = None,
    recurrence_rules: list[dict[str, Any]] | None = None,
    alerts: list[str] | None = None,
    use_default_alerts: bool | None = None,
    google_color_id: str | None = None,
    series_update_mode: Literal["single", "future", "all"] = "single",
) -> MutateEventResult:
    """Update an existing calendar event.

    Only include fields you want to change. Note that when updating timing
    fields (start, duration, time_zone, is_all_day), you must provide all four.

    Args:
        event_id: The virtual ID of the event to update.
        title: New event title.
        start: New start time in LocalDateTime format.
        duration: New duration in ISO 8601 format.
        time_zone: New IANA timezone.
        is_all_day: New all-day status.
        description: New description.
        location: New location name (set to empty string to remove).
        free_busy_status: New free/busy status.
        privacy: New privacy setting.
        recurrence_rules: New recurrence rules. Pass an empty list to clear.
            See create_event for the dict shape.
        alerts: Replace alerts with these negative ISO 8601 offsets
            (e.g., ['-PT15M']). Cannot be combined with use_default_alerts.
        use_default_alerts: If True, switch to the calendar's default alerts.
        google_color_id: Google Calendar color ID, "1" through "11".
        series_update_mode: For recurring events - "single", "future", or "all".

    Returns:
        Dictionary indicating success or error.
    """
    real_event_id = _resolve_event_id(event_id)
    _validate_event_update_fields(
        start=start,
        duration=duration,
        time_zone=time_zone,
        is_all_day=is_all_day,
        alerts=alerts,
        use_default_alerts=use_default_alerts,
        google_color_id=google_color_id,
    )

    real_account_id, real_calendar_id = extract_ids_from_event(real_event_id)

    request = EventUpdateRequest(
        id=real_event_id,
        account_id=real_account_id,
        calendar_id=real_calendar_id,
        title=title,
        start=start,
        duration=duration,
        time_zone=time_zone,
        show_without_time=is_all_day,
        description=description,
        locations=build_locations_dict(location, allow_empty=True),
        alerts=build_alerts_dict(alerts),
        use_default_alerts=use_default_alerts,
        free_busy_status=free_busy_status,
        privacy=privacy,
        recurrence_rules=build_recurrence_rules(recurrence_rules),
        google_color_id=google_color_id,
    )

    client = get_client()
    try:
        await client.update_event(request, series_update_mode=series_update_mode)
    except MorgenAPIError as e:
        if is_not_found(e):
            raise ToolError(_EVENT_GONE.format(id=event_id)) from e
        raise

    return {
        "success": True,
        "message": "Event updated successfully.",
        "eventId": event_id,
        "seriesUpdateMode": series_update_mode,
    }


@handle_tool_errors
async def delete_event(
    event_id: str,
    series_update_mode: Literal["single", "future", "all"] = "single",
) -> DeleteEventResult:
    """Delete a calendar event.

    Args:
        event_id: The virtual ID of the event to delete.
        series_update_mode: For recurring events - "single", "future", or "all".

    Returns:
        Dictionary indicating success. With series_update_mode="single",
        deleting is idempotent: if the event is already gone (Morgen answers
        404 — deleted, cancelled, or no longer retrievable), the call still
        succeeds and sets alreadyGone=True, meaning nothing was removed. With
        "future" or "all" that 404 is an error, since other occurrences may
        remain.
    """
    # Resolve virtual event ID and extract account/calendar IDs
    real_event_id = _resolve_event_id(event_id)
    real_account_id, real_calendar_id = extract_ids_from_event(real_event_id)

    request = EventDeleteRequest(
        id=real_event_id,
        account_id=real_account_id,
        calendar_id=real_calendar_id,
    )

    client = get_client()
    try:
        await client.delete_event(request, series_update_mode=series_update_mode)
    except MorgenAPIError as e:
        # events.mdx: a repeated delete returns 404, not 204, and callers
        # should treat it as success, but only for the targeted occurrence.
        if not is_not_found(e):
            raise
        error = _delete_not_found_error(event_id, series_update_mode)
        if error:
            raise ToolError(error) from e
        return {
            "success": True,
            "message": _EVENT_ALREADY_GONE_MESSAGE,
            "eventId": event_id,
            "seriesUpdateMode": series_update_mode,
            "alreadyGone": True,
        }

    return {
        "success": True,
        "message": "Event deleted successfully.",
        "eventId": event_id,
        "seriesUpdateMode": series_update_mode,
    }


@handle_tool_errors
async def batch_delete_events(
    event_ids: list[str],
    series_update_mode: Literal["single", "future", "all"] = "single",
    ctx: Context | None = None,
) -> BatchDeleteEventsResult:
    """Delete multiple calendar events in a single tool call.

    Args:
        event_ids: List of virtual event IDs to delete.
        series_update_mode: For recurring events - "single", "future", or "all".

    Returns:
        Dictionary with 'deleted' (list of virtual IDs), 'failed' (list of
        {id, error}) and, when any were present, 'alreadyGone' (virtual IDs
        Morgen answered 404 for: already deleted, cancelled, or no longer
        retrievable — not failures, but nothing was removed for them). Only
        series_update_mode="single" reports 404s as alreadyGone; with
        "future" or "all" they are failures, since other occurrences may
        remain.
    """
    if not event_ids:
        return {"deleted": [], "failed": [], "message": "No events to delete."}

    client = get_client()
    deleted: list[str] = []
    failed: list[FailedItem] = []
    already_gone: list[str] = []

    # Prepare delete operations
    to_delete: list[
        tuple[str, str, str, str]
    ] = []  # (virtual_id, real_event_id, real_account_id, real_calendar_id)
    for virtual_event_id in event_ids:
        try:
            real_event_id = _resolve_event_id(virtual_event_id)
            real_account_id, real_calendar_id = extract_ids_from_event(real_event_id)
            to_delete.append(
                (virtual_event_id, real_event_id, real_account_id, real_calendar_id)
            )
        except Exception as e:
            failed.append({"id": virtual_event_id, "error": str(e)})

    # Delete events in parallel
    async def delete_single(
        real_event_id: str, real_account_id: str, real_calendar_id: str
    ) -> None:
        request = EventDeleteRequest(
            id=real_event_id,
            account_id=real_account_id,
            calendar_id=real_calendar_id,
        )
        await client.delete_event(request, series_update_mode=series_update_mode)

    results = await gather_bounded(
        delete_single(real_event_id, real_account_id, real_calendar_id)
        for _, real_event_id, real_account_id, real_calendar_id in to_delete
    )

    for i, result in enumerate(results):
        virtual_event_id = to_delete[i][0]
        if is_not_found(result):
            error = _delete_not_found_error(virtual_event_id, series_update_mode)
            if error is None:
                already_gone.append(virtual_event_id)
                continue
            if ctx:
                await ctx.warning(error)
            failed.append({"id": virtual_event_id, "error": error})
        elif isinstance(result, BaseException):
            error = str(result) or type(result).__name__
            if ctx:
                await ctx.warning(f"Failed to delete event {virtual_event_id}: {error}")
            failed.append({"id": virtual_event_id, "error": error})
        else:
            deleted.append(virtual_event_id)

    summary = f"Deleted {len(deleted)}, failed {len(failed)}"
    batch_result: BatchDeleteEventsResult = {
        "deleted": deleted,
        "failed": failed,
        "summary": summary,
    }
    if already_gone:
        batch_result["alreadyGone"] = already_gone
        batch_result["summary"] = f"{summary}, already gone {len(already_gone)}"
    return batch_result


@handle_tool_errors
async def batch_update_events(
    updates: list[dict[str, Any]],
    series_update_mode: Literal["single", "future", "all"] = "single",
    ctx: Context | None = None,
) -> BatchUpdateResult:
    """Update multiple calendar events in a single tool call.

    Args:
        updates: List of update dicts. Each must have 'event_id' (virtual ID) and optional fields:
            title, start, duration, time_zone, is_all_day, description, location,
            free_busy_status, privacy.
        series_update_mode: For recurring events - "single", "future", or "all".

    Returns:
        Dictionary with 'updated' (list of virtual IDs) and 'failed' (list of {id, error}).
    """
    if not updates:
        return {"updated": [], "failed": [], "message": "No updates to apply."}

    client = get_client()
    updated: list[str] = []
    failed: list[FailedItem] = []

    # Validate and prepare updates. Everything that can be rejected from the
    # input alone is rejected here, so those failures never reach the API (and
    # never emit ctx.warning, which is reserved for upstream failures).
    to_update: list[tuple[str, EventUpdateRequest]] = []
    for update in updates:
        virtual_event_id = update.get("event_id")
        if virtual_event_id is None:
            failed.append({"id": "(unknown)", "error": "Missing event_id in update"})
            continue
        if not isinstance(virtual_event_id, str):
            failed.append({"id": "(unknown)", "error": "event_id must be a string"})
            continue

        try:
            real_event_id = _resolve_event_id(virtual_event_id)
            update_alerts = update.get("alerts")
            update_default = update.get("use_default_alerts")
            _validate_event_update_fields(
                start=update.get("start"),
                duration=update.get("duration"),
                time_zone=update.get("time_zone"),
                is_all_day=update.get("is_all_day"),
                alerts=update_alerts,
                use_default_alerts=update_default,
                google_color_id=update.get("google_color_id"),
            )
            real_account_id, real_calendar_id = extract_ids_from_event(real_event_id)
            request = EventUpdateRequest(
                id=real_event_id,
                account_id=real_account_id,
                calendar_id=real_calendar_id,
                title=update.get("title"),
                start=update.get("start"),
                duration=update.get("duration"),
                time_zone=update.get("time_zone"),
                show_without_time=update.get("is_all_day"),
                description=update.get("description"),
                locations=build_locations_dict(
                    update.get("location"), allow_empty=True
                ),
                alerts=build_alerts_dict(update_alerts),
                use_default_alerts=update_default,
                free_busy_status=update.get("free_busy_status"),
                privacy=update.get("privacy"),
                recurrence_rules=build_recurrence_rules(update.get("recurrence_rules")),
                google_color_id=update.get("google_color_id"),
            )
            to_update.append((virtual_event_id, request))
        except Exception as e:
            failed.append({"id": virtual_event_id, "error": str(e)})

    # Apply updates in parallel
    results = await gather_bounded(
        client.update_event(request, series_update_mode=series_update_mode)
        for _, request in to_update
    )

    for i, result in enumerate(results):
        virtual_event_id = to_update[i][0]
        if not isinstance(result, BaseException):
            updated.append(virtual_event_id)
            continue
        if is_not_found(result):
            error = warning = _EVENT_GONE.format(id=virtual_event_id)
        else:
            error = str(result) or type(result).__name__
            warning = f"Failed to update event {virtual_event_id}: {error}"
        if ctx:
            await ctx.warning(warning)
        failed.append({"id": virtual_event_id, "error": error})

    return {
        "updated": updated,
        "failed": failed,
        "summary": f"Updated {len(updated)}, failed {len(failed)}",
    }
