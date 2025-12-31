"""FastMCP server for Morgen calendar API."""

from dotenv import load_dotenv

load_dotenv()  # Load .env from CWD if present

from typing import Literal

from fastmcp import FastMCP

from morgenmcp.tools.calendars import list_calendars, update_calendar_metadata
from morgenmcp.tools.events import create_event, delete_event, list_events, update_event

# Create the MCP server
mcp = FastMCP(
    "morgen-calendar",
    instructions="""
    Morgen Calendar MCP Server provides access to Morgen's unified calendar API.

    Use list_calendars to discover available calendars and their IDs.
    Use list_events to retrieve events from specific calendars within a time window.
    Use create_event, update_event, and delete_event to manage calendar events.

    Important notes:
    - All calendar operations require accountId and calendarId from list_calendars
    - Times are in LocalDateTime format (e.g., "2023-03-01T10:15:00") with separate timeZone
    - Durations use ISO 8601 format (e.g., "PT1H" for 1 hour, "PT30M" for 30 minutes)
    - For recurring events, use seriesUpdateMode to control how updates affect the series
    """,
)


# Register calendar tools
@mcp.tool()
async def morgen_list_calendars() -> dict:
    """List all calendars across connected calendar accounts.

    Returns a list of calendars with their IDs, names, colors, and permissions.
    Use this first to discover available calendars before listing events.
    """
    return await list_calendars()


@mcp.tool()
async def morgen_update_calendar_metadata(
    calendar_id: str,
    account_id: str,
    busy: bool | None = None,
    override_color: str | None = None,
    override_name: str | None = None,
) -> dict:
    """Update Morgen-specific metadata for a calendar.

    Args:
        calendar_id: The ID of the calendar to update.
        account_id: The ID of the account the calendar belongs to.
        busy: Whether events from this calendar count toward availability.
        override_color: Custom color for the calendar (hex format, e.g., "#ff0000").
        override_name: Custom display name for the calendar.
    """
    return await update_calendar_metadata(
        calendar_id=calendar_id,
        account_id=account_id,
        busy=busy,
        override_color=override_color,
        override_name=override_name,
    )


# Register event tools
@mcp.tool()
async def morgen_list_events(
    account_id: str,
    calendar_ids: list[str],
    start: str,
    end: str,
) -> dict:
    """List events from specified calendars within a time window.

    Recurring events are automatically expanded to individual occurrences.

    Args:
        account_id: The calendar account ID (from list_calendars).
        calendar_ids: List of calendar IDs (must all belong to the same account).
        start: Start of time window in ISO 8601 format (e.g., "2023-03-01T00:00:00Z").
        end: End of time window in ISO 8601 format. Max 6 months from start.
    """
    return await list_events(
        account_id=account_id,
        calendar_ids=calendar_ids,
        start=start,
        end=end,
    )


@mcp.tool()
async def morgen_create_event(
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
        duration: Duration in ISO 8601 format (e.g., "PT1H" for 1 hour).
        time_zone: IANA timezone (e.g., "Europe/Berlin"). Use None for floating events.
        is_all_day: True for all-day events, False for timed events.
        description: Optional event description.
        location: Optional location name.
        participants: Optional list of participant email addresses to invite.
        free_busy_status: "free" or "busy" (default: "busy").
        privacy: "public", "private", or "secret" (default: "public").
        request_virtual_room: Request automatic video room creation.
    """
    return await create_event(
        account_id=account_id,
        calendar_id=calendar_id,
        title=title,
        start=start,
        duration=duration,
        time_zone=time_zone,
        is_all_day=is_all_day,
        description=description,
        location=location,
        participants=participants,
        free_busy_status=free_busy_status,
        privacy=privacy,
        request_virtual_room=request_virtual_room,
    )


@mcp.tool()
async def morgen_update_event(
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

    Only include fields you want to change. When updating timing fields
    (start, duration, time_zone, is_all_day), all four must be provided.

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
        location: New location name (empty string to remove).
        free_busy_status: New free/busy status.
        privacy: New privacy setting.
        series_update_mode: For recurring events - "single", "future", or "all".
    """
    return await update_event(
        event_id=event_id,
        account_id=account_id,
        calendar_id=calendar_id,
        title=title,
        start=start,
        duration=duration,
        time_zone=time_zone,
        is_all_day=is_all_day,
        description=description,
        location=location,
        free_busy_status=free_busy_status,
        privacy=privacy,
        series_update_mode=series_update_mode,
    )


@mcp.tool()
async def morgen_delete_event(
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
    """
    return await delete_event(
        event_id=event_id,
        account_id=account_id,
        calendar_id=calendar_id,
        series_update_mode=series_update_mode,
    )


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
