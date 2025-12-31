"""MCP tools for Morgen event operations."""

from typing import Literal

from morgenmcp.client import get_client
from morgenmcp.models import (
    EventCreateRequest,
    EventDeleteRequest,
    EventUpdateRequest,
    Location,
    MorgenAPIError,
    Participant,
    ParticipantRoles,
)
from morgenmcp.validators import (
    ValidationError,
    validate_date_range,
    validate_duration,
    validate_email,
    validate_local_datetime,
    validate_timezone,
)


async def list_events(
    account_id: str,
    calendar_ids: list[str],
    start: str,
    end: str,
) -> dict:
    """List events from specified calendars within a time window.

    Recurring events are automatically expanded to individual occurrences.
    Deleted or cancelled events are not included.

    Args:
        account_id: The calendar account ID to retrieve events from.
        calendar_ids: List of calendar IDs (must all belong to the same account).
        start: Start of time window in LocalDateTime format (e.g., "2023-03-01T00:00:00").
        end: End of time window in LocalDateTime format. Max 6 months from start.

    Returns:
        Dictionary with 'events' key containing list of event objects.
    """
    try:
        # Validate inputs
        validate_local_datetime(start, "start")
        validate_local_datetime(end, "end")
        validate_date_range(start, end)

        if not calendar_ids:
            return {"error": "calendar_ids cannot be empty"}

        client = get_client()
        events = await client.list_events(
            account_id=account_id,
            calendar_ids=calendar_ids,
            start=start,
            end=end,
        )

        return {
            "events": [
                {
                    "id": event.id,
                    "calendarId": event.calendar_id,
                    "accountId": event.account_id,
                    "title": event.title,
                    "description": event.description,
                    "start": event.start,
                    "duration": event.duration,
                    "timeZone": event.time_zone,
                    "isAllDay": event.show_without_time,
                    "status": event.free_busy_status,
                    "privacy": event.privacy,
                    "locations": [
                        {"name": loc.name}
                        for loc in (event.locations or {}).values()
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
                    "recurrenceId": event.recurrence_id,
                    "masterEventId": event.master_event_id,
                    "virtualRoomUrl": (
                        event.derived.virtual_room.url
                        if event.derived and event.derived.virtual_room
                        else None
                    ),
                }
                for event in events
            ],
            "count": len(events),
        }
    except ValidationError as e:
        return {"error": str(e), "validation_error": True}
    except MorgenAPIError as e:
        return {
            "error": str(e),
            "status_code": e.status_code,
        }
    except Exception as e:
        return {
            "error": f"Unexpected error: {e}",
        }


async def create_event(
    account_id: str,
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
    request_virtual_room: Literal["default", "googleMeet", "microsoftTeams"] | None = None,
) -> dict:
    """Create a new calendar event.

    Args:
        account_id: The ID of the account to create the event in.
        calendar_id: The ID of the calendar to create the event in.
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

    Returns:
        Dictionary with created event ID and details.
    """
    try:
        # Validate inputs
        validate_local_datetime(start, "start")
        validate_duration(duration)
        validate_timezone(time_zone)

        if participants:
            for email in participants:
                validate_email(email)

        # Build locations dict if provided
        locations_dict = None
        if location:
            locations_dict = {"1": Location(name=location)}

        # Build participants dict if provided
        participants_dict = None
        if participants:
            participants_dict = {
                email: Participant(
                    name=email.split("@")[0],  # Use email prefix as name
                    email=email,
                    roles=ParticipantRoles(attendee=True),
                    participation_status="needs-action",
                )
                for email in participants
            }

        request = EventCreateRequest(
            account_id=account_id,
            calendar_id=calendar_id,
            title=title,
            start=start,
            duration=duration,
            time_zone=time_zone,
            show_without_time=is_all_day,
            description=description,
            locations=locations_dict,
            participants=participants_dict,
            free_busy_status=free_busy_status,
            privacy=privacy,
            request_virtual_room=request_virtual_room,
        )

        client = get_client()
        response = await client.create_event(request)

        return {
            "success": True,
            "message": "Event created successfully.",
            "event": {
                "id": response.id,
                "calendarId": response.calendar_id,
                "accountId": response.account_id,
            },
        }
    except ValidationError as e:
        return {"error": str(e), "validation_error": True}
    except MorgenAPIError as e:
        return {
            "error": str(e),
            "status_code": e.status_code,
        }
    except Exception as e:
        return {
            "error": f"Unexpected error: {e}",
        }


async def update_event(
    event_id: str,
    account_id: str,
    calendar_id: str,
    title: str | None = None,
    start: str | None = None,
    duration: str | None = None,
    time_zone: str | None = None,
    is_all_day: bool | None = None,
    description: str | None = None,
    location: str | None = None,
    free_busy_status: Literal["free", "busy"] | None = None,
    privacy: Literal["public", "private", "secret"] | None = None,
    series_update_mode: Literal["single", "future", "all"] = "single",
) -> dict:
    """Update an existing calendar event.

    Only include fields you want to change. Note that when updating timing
    fields (start, duration, time_zone, is_all_day), you must provide all four.

    Args:
        event_id: The Morgen ID of the event to update.
        account_id: The ID of the account the event belongs to.
        calendar_id: The ID of the calendar the event belongs to.
        title: New event title.
        start: New start time in LocalDateTime format.
        duration: New duration in ISO 8601 format.
        time_zone: New IANA timezone.
        is_all_day: New all-day status.
        description: New description.
        location: New location name (set to empty string to remove).
        free_busy_status: New free/busy status.
        privacy: New privacy setting.
        series_update_mode: For recurring events - "single", "future", or "all".

    Returns:
        Dictionary indicating success or error.
    """
    # Validate timing fields constraint
    timing_fields = [start, duration, time_zone, is_all_day]
    timing_provided = [f for f in timing_fields if f is not None]
    if timing_provided and len(timing_provided) != 4:
        return {
            "error": "When updating timing fields (start, duration, time_zone, is_all_day), "
            "all four must be provided together.",
        }

    try:
        # Validate inputs if provided
        if start is not None:
            validate_local_datetime(start, "start")
        if duration is not None:
            validate_duration(duration)
        if time_zone is not None:
            validate_timezone(time_zone)

        # Build locations dict if provided
        locations_dict = None
        if location is not None:
            if location:
                locations_dict = {"1": Location(name=location)}
            else:
                # Empty string means remove all locations
                locations_dict = {}

        request = EventUpdateRequest(
            id=event_id,
            account_id=account_id,
            calendar_id=calendar_id,
            title=title,
            start=start,
            duration=duration,
            time_zone=time_zone,
            show_without_time=is_all_day,
            description=description,
            locations=locations_dict,
            free_busy_status=free_busy_status,
            privacy=privacy,
        )

        client = get_client()
        await client.update_event(request, series_update_mode=series_update_mode)

        return {
            "success": True,
            "message": "Event updated successfully.",
            "eventId": event_id,
            "seriesUpdateMode": series_update_mode,
        }
    except ValidationError as e:
        return {"error": str(e), "validation_error": True}
    except MorgenAPIError as e:
        return {
            "error": str(e),
            "status_code": e.status_code,
        }
    except Exception as e:
        return {
            "error": f"Unexpected error: {e}",
        }


async def delete_event(
    event_id: str,
    account_id: str,
    calendar_id: str,
    series_update_mode: Literal["single", "future", "all"] = "single",
) -> dict:
    """Delete a calendar event.

    Args:
        event_id: The Morgen ID of the event to delete.
        account_id: The ID of the account the event belongs to.
        calendar_id: The ID of the calendar the event belongs to.
        series_update_mode: For recurring events - "single", "future", or "all".

    Returns:
        Dictionary indicating success or error.
    """
    try:
        request = EventDeleteRequest(
            id=event_id,
            account_id=account_id,
            calendar_id=calendar_id,
        )

        client = get_client()
        await client.delete_event(request, series_update_mode=series_update_mode)

        return {
            "success": True,
            "message": "Event deleted successfully.",
            "eventId": event_id,
            "seriesUpdateMode": series_update_mode,
        }
    except MorgenAPIError as e:
        return {
            "error": str(e),
            "status_code": e.status_code,
        }
    except Exception as e:
        return {
            "error": f"Unexpected error: {e}",
        }
