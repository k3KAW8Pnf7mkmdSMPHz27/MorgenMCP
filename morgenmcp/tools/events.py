"""MCP tools for Morgen event operations."""

import asyncio
import os
from collections import defaultdict
from datetime import datetime, timedelta, tzinfo
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastmcp import Context
from fastmcp.exceptions import ToolError

from morgenmcp.client import get_client
from morgenmcp.models import (
    Event,
    EventCreateRequest,
    EventDeleteRequest,
    EventUpdateRequest,
)
from morgenmcp.tools.id_registry import register_id, resolve_id, resolve_ids
from morgenmcp.tools.id_utils import (
    extract_account_from_calendar,
    extract_ids_from_event,
)
from morgenmcp.tools.utils import (
    build_alerts_dict,
    build_locations_dict,
    build_participants_dict,
    build_recurrence_rules,
    filter_none_values,
    handle_tool_errors,
)
from morgenmcp.validators import (
    validate_date_range,
    validate_duration,
    validate_email,
    validate_local_datetime,
    validate_timezone,
)

_DISPLAY_TZ_ENV = "MORGENMCP_DISPLAY_TZ"


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
    sys_tz = datetime.now().astimezone().tzinfo
    assert sys_tz is not None
    return sys_tz


def _tz_label(dt: datetime, tz: tzinfo) -> str:
    """Render '<abbrev> (<IANA>)' or just '<label>' on fixed-offset fallbacks."""
    iana = getattr(tz, "key", None) or str(tz)
    abbrev = dt.tzname() or iana
    if abbrev == iana:
        return iana
    return f"{abbrev} ({iana})"


def _format_compact_event(event: Event, display_tz: tzinfo) -> str:
    """Format an event in compact one-liner format with virtual ID.

    Times are converted from the event's `time_zone` into `display_tz` and
    tagged with the abbreviation plus IANA name. Floating events (no source
    timezone) are tagged "(floating)" and not converted. All-day events keep
    the existing "<MMM DD> (all-day)" form.
    """
    virtual_id = register_id(event.id)
    title = event.title or "(No title)"

    if event.show_without_time:
        # All-day event: "Mar 15 (all-day): Holiday [abc123]"
        try:
            dt = datetime.fromisoformat(event.start)
            date_str = dt.strftime("%b %d")
        except ValueError, TypeError:
            date_str = event.start
        return f"{date_str} (all-day): {title} [{virtual_id}]"

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
            start_str = start_naive.strftime("%H:%M")
            end_str = end_naive.strftime("%H:%M")
            cross = end_naive.date() != start_naive.date()
            end_label = f"{end_naive.strftime('%b %d')} {end_str}" if cross else end_str
            return f"{start_str}-{end_label} (floating): {title} [{virtual_id}]"

        try:
            source_tz = ZoneInfo(event.time_zone)
        except Exception:
            return f"{event.start} {event.time_zone}: {title} [{virtual_id}]"

        start_dt = start_naive.replace(tzinfo=source_tz).astimezone(display_tz)
        end_dt = end_naive.replace(tzinfo=source_tz).astimezone(display_tz)

        start_str = start_dt.strftime("%H:%M")
        end_str = end_dt.strftime("%H:%M")
        cross = end_dt.date() != start_dt.date()
        end_label = f"{end_dt.strftime('%b %d')} {end_str}" if cross else end_str
        return (
            f"{start_str}-{end_label} {_tz_label(start_dt, display_tz)}: "
            f"{title} [{virtual_id}]"
        )
    except ValueError, TypeError:
        return f"{event.start}: {title} [{virtual_id}]"


def _format_recurrence_rule(rule: Any) -> dict[str, Any]:
    """Compact representation of a recurrence rule."""
    return filter_none_values(
        {
            "frequency": rule.frequency,
            "interval": rule.interval,
            "byDay": [d.day for d in (rule.by_day or [])] or None,
        }
    )


def _format_alerts(event: Event) -> list[dict[str, str]] | None:
    """Compact representation of an event's alerts as offset list."""
    alerts = event.alerts or {}
    if not alerts:
        return None
    out: list[dict[str, str]] = []
    for alert in alerts.values():
        if alert and alert.trigger:
            out.append({"offset": alert.trigger.offset, "action": alert.action})
    return out or None


def _format_full_event(event: Event) -> dict[str, Any]:
    """Format an event in full format with all fields and virtual IDs."""
    metadata = event.metadata
    return filter_none_values(
        {
            "id": register_id(event.id),
            "calendarId": register_id(event.calendar_id),
            "accountId": register_id(event.account_id),
            "title": event.title,
            "description": event.description,
            "start": event.start,
            "duration": event.duration,
            "timeZone": event.time_zone,
            "isAllDay": event.show_without_time,
            "status": event.free_busy_status,
            "privacy": event.privacy,
            "locations": [
                {"name": loc.name} for loc in (event.locations or {}).values()
            ],
            "participants": [
                {
                    "name": p.name,
                    "email": p.email,
                    "status": p.participation_status,
                    "isOrganizer": p.roles.owner if p.roles else False,
                }
                for p in (event.participants or {}).values()
            ],
            "isRecurring": event.recurrence_rules is not None,
            "recurrenceRules": [
                _format_recurrence_rule(r) for r in (event.recurrence_rules or [])
            ]
            or None,
            "recurrenceId": event.recurrence_id,
            "masterEventId": register_id(event.master_event_id)
            if event.master_event_id
            else None,
            "alerts": _format_alerts(event),
            "useDefaultAlerts": event.use_default_alerts or None,
            "googleColorId": event.google_color_id,
            "categoryId": metadata.category_id if metadata else None,
            "categoryName": metadata.category_name if metadata else None,
            "categoryColor": metadata.category_color if metadata else None,
            "taskId": register_id(metadata.task_id)
            if metadata and metadata.task_id
            else None,
            "virtualRoomUrl": (
                event.derived.virtual_room.url
                if event.derived and event.derived.virtual_room
                else None
            ),
        }
    )


@handle_tool_errors
async def list_events(
    start: str,
    end: str,
    calendar_ids: list[str] | None = None,
    compact: bool = False,
    display_timezone: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """List events from calendars within a time window.

    Recurring events are automatically expanded to individual occurrences.
    Deleted or cancelled events are not included.

    Args:
        start: Start of time window in LocalDateTime format (e.g., "2023-03-01T00:00:00").
        end: End of time window in LocalDateTime format. Max 6 months from start.
        calendar_ids: Optional list of virtual calendar IDs. If omitted, queries all calendars.
        compact: If True, returns compact one-liner format to reduce tokens.
            Format: "09:15-10:00 CDT (America/Chicago): Meeting [event_id]"
        display_timezone: Optional IANA timezone (e.g. "America/Chicago") used to
            render compact times. Defaults to the MORGENMCP_DISPLAY_TZ env var,
            or the system local timezone if unset. Only affects compact=True
            output; floating events are tagged "(floating)".

    Returns:
        Dictionary with 'events' key containing list of event objects (or strings if compact).
    """
    validate_local_datetime(start, "start")
    validate_local_datetime(end, "end")
    validate_date_range(start, end)
    validate_timezone(display_timezone)

    client = get_client()
    all_events: list[Event] = []

    if calendar_ids is not None:
        # Specific calendars requested - resolve virtual IDs and extract account
        if not calendar_ids:
            raise ToolError("calendar_ids cannot be empty when provided")

        real_calendar_ids = resolve_ids(calendar_ids)
        # Extract account ID from first calendar (all calendars in a query must be from same account)
        real_account_id = extract_account_from_calendar(real_calendar_ids[0])

        all_events = await client.list_events(
            account_id=real_account_id,
            calendar_ids=real_calendar_ids,
            start=start,
            end=end,
        )
    else:
        # Fetch all calendars and query by account
        calendars = await client.list_calendars()

        # Group calendars by account_id (using real IDs internally)
        calendars_by_account: dict[str, list[str]] = defaultdict(list)
        for cal in calendars:
            calendars_by_account[cal.account_id].append(cal.id)

        # Query events for each account in parallel
        async def fetch_account_events(acc_id: str, cal_ids: list[str]) -> list[Event]:
            return await client.list_events(
                account_id=acc_id,
                calendar_ids=cal_ids,
                start=start,
                end=end,
            )

        tasks = [
            fetch_account_events(acc_id, cal_ids)
            for acc_id, cal_ids in calendars_by_account.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        account_ids = list(calendars_by_account.keys())
        for i, result in enumerate(results):
            if ctx:
                await ctx.report_progress(i + 1, len(results))
            if isinstance(result, BaseException):
                if ctx:
                    await ctx.warning(
                        f"Failed to fetch events for account {account_ids[i]}: {result}"
                    )
                continue
            all_events.extend(result)

    # Format output (IDs are registered during formatting)
    if compact:
        display_tz = _resolve_display_tz(display_timezone)
        return {
            "events": [
                _format_compact_event(event, display_tz) for event in all_events
            ],
            "count": len(all_events),
        }
    else:
        return {
            "events": [_format_full_event(event) for event in all_events],
            "count": len(all_events),
        }


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
) -> dict:
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

    if google_color_id is not None and google_color_id not in {
        str(i) for i in range(1, 12)
    }:
        raise ToolError("google_color_id must be a string '1' through '11'")

    # Resolve virtual calendar ID and extract account ID
    real_calendar_id = resolve_id(calendar_id)
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
) -> dict:
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
    # Validate timing fields constraint
    timing_fields = [start, duration, time_zone, is_all_day]
    timing_provided = [f for f in timing_fields if f is not None]
    if timing_provided and len(timing_provided) != 4:
        raise ToolError(
            "When updating timing fields (start, duration, time_zone, is_all_day), "
            "all four must be provided together."
        )

    # Validate inputs if provided
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

    if google_color_id is not None and google_color_id not in {
        str(i) for i in range(1, 12)
    }:
        raise ToolError("google_color_id must be a string '1' through '11'")

    # Resolve virtual event ID and extract account/calendar IDs
    real_event_id = resolve_id(event_id)
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
    await client.update_event(request, series_update_mode=series_update_mode)

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
) -> dict:
    """Delete a calendar event.

    Args:
        event_id: The virtual ID of the event to delete.
        series_update_mode: For recurring events - "single", "future", or "all".

    Returns:
        Dictionary indicating success or error.
    """
    # Resolve virtual event ID and extract account/calendar IDs
    real_event_id = resolve_id(event_id)
    real_account_id, real_calendar_id = extract_ids_from_event(real_event_id)

    request = EventDeleteRequest(
        id=real_event_id,
        account_id=real_account_id,
        calendar_id=real_calendar_id,
    )

    client = get_client()
    await client.delete_event(request, series_update_mode=series_update_mode)

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
) -> dict:
    """Delete multiple calendar events in a single tool call.

    Args:
        event_ids: List of virtual event IDs to delete.
        series_update_mode: For recurring events - "single", "future", or "all".

    Returns:
        Dictionary with 'deleted' (list of virtual IDs) and 'failed' (list of {id, error}).
    """
    if not event_ids:
        return {"deleted": [], "failed": [], "message": "No events to delete."}

    client = get_client()
    deleted: list[str] = []
    failed: list[dict[str, str]] = []

    # Prepare delete operations
    to_delete: list[
        tuple[str, str, str, str]
    ] = []  # (virtual_id, real_event_id, real_account_id, real_calendar_id)
    for virtual_event_id in event_ids:
        try:
            real_event_id = resolve_id(virtual_event_id)
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

    tasks = [
        delete_single(real_event_id, real_account_id, real_calendar_id)
        for virtual_event_id, real_event_id, real_account_id, real_calendar_id in to_delete
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        virtual_event_id = to_delete[i][0]
        if isinstance(result, Exception):
            if ctx:
                await ctx.warning(
                    f"Failed to delete event {virtual_event_id}: {result}"
                )
            failed.append({"id": virtual_event_id, "error": str(result)})
        else:
            deleted.append(virtual_event_id)

    return {
        "deleted": deleted,
        "failed": failed,
        "summary": f"Deleted {len(deleted)}, failed {len(failed)}",
    }


@handle_tool_errors
async def batch_update_events(
    updates: list[dict[str, Any]],
    series_update_mode: Literal["single", "future", "all"] = "single",
    ctx: Context | None = None,
) -> dict:
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
    failed: list[dict[str, str]] = []

    # Validate and prepare updates
    to_update: list[
        tuple[str, str, str, str, dict[str, Any]]
    ] = []  # (virtual_id, real_event_id, real_account_id, real_calendar_id, update)
    for update in updates:
        virtual_event_id = update.get("event_id")
        if not virtual_event_id:
            failed.append({"id": "(unknown)", "error": "Missing event_id in update"})
            continue

        # Validate timing fields constraint
        timing_fields = ["start", "duration", "time_zone", "is_all_day"]
        timing_provided = [f for f in timing_fields if update.get(f) is not None]
        if timing_provided and len(timing_provided) != 4:
            failed.append(
                {
                    "id": virtual_event_id,
                    "error": "When updating timing fields, all four (start, duration, "
                    "time_zone, is_all_day) must be provided together.",
                }
            )
            continue

        try:
            real_event_id = resolve_id(virtual_event_id)
            real_account_id, real_calendar_id = extract_ids_from_event(real_event_id)
            to_update.append(
                (
                    virtual_event_id,
                    real_event_id,
                    real_account_id,
                    real_calendar_id,
                    update,
                )
            )
        except Exception as e:
            failed.append({"id": virtual_event_id, "error": str(e)})

    # Apply updates in parallel
    async def update_single(
        real_event_id: str,
        real_account_id: str,
        real_calendar_id: str,
        update: dict[str, Any],
    ) -> None:
        # Validate inputs
        if update.get("start"):
            validate_local_datetime(update["start"], "start")
        if update.get("duration"):
            validate_duration(update["duration"])
        if update.get("time_zone"):
            validate_timezone(update["time_zone"])

        update_alerts = update.get("alerts")
        update_default = update.get("use_default_alerts")
        if update_alerts and update_default:
            raise ToolError(
                "alerts and use_default_alerts are mutually exclusive — pick one."
            )

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
            locations=build_locations_dict(update.get("location"), allow_empty=True),
            alerts=build_alerts_dict(update_alerts),
            use_default_alerts=update_default,
            free_busy_status=update.get("free_busy_status"),
            privacy=update.get("privacy"),
            recurrence_rules=build_recurrence_rules(update.get("recurrence_rules")),
            google_color_id=update.get("google_color_id"),
        )
        await client.update_event(request, series_update_mode=series_update_mode)

    tasks = [
        update_single(real_event_id, real_account_id, real_calendar_id, update)
        for virtual_event_id, real_event_id, real_account_id, real_calendar_id, update in to_update
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        virtual_event_id = to_update[i][0]
        if isinstance(result, Exception):
            if ctx:
                await ctx.warning(
                    f"Failed to update event {virtual_event_id}: {result}"
                )
            failed.append({"id": virtual_event_id, "error": str(result)})
        else:
            updated.append(virtual_event_id)

    return {
        "updated": updated,
        "failed": failed,
        "summary": f"Updated {len(updated)}, failed {len(failed)}",
    }
