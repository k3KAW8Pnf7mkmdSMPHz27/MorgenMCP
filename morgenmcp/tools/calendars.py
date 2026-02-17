"""MCP tools for Morgen calendar operations."""

from morgenmcp.client import get_client
from morgenmcp.tools.id_registry import register_id, resolve_id
from morgenmcp.tools.id_utils import extract_account_from_calendar
from morgenmcp.tools.utils import filter_none_values, handle_tool_errors
from morgenmcp.validators import validate_hex_color


def _format_calendar(cal) -> dict:
    """Format a calendar object, filtering out null values and virtualizing IDs."""
    return filter_none_values(
        {
            "id": register_id(cal.id),
            "accountId": register_id(cal.account_id),
            "integrationId": cal.integration_id,
            "name": cal.name,
            "color": cal.color,
            "sortOrder": cal.sort_order,
            "permissions": filter_none_values(
                {
                    "canRead": cal.my_rights.may_read_items if cal.my_rights else None,
                    "canWrite": cal.my_rights.may_write_all if cal.my_rights else None,
                    "canDelete": cal.my_rights.may_delete if cal.my_rights else None,
                }
            )
            if cal.my_rights
            else None,
            "metadata": filter_none_values(
                {
                    "busy": cal.metadata.busy if cal.metadata else None,
                    "overrideColor": cal.metadata.override_color
                    if cal.metadata
                    else None,
                    "overrideName": cal.metadata.override_name
                    if cal.metadata
                    else None,
                }
            )
            if cal.metadata
            else None,
        }
    )


@handle_tool_errors
async def list_calendars() -> dict:
    """List all calendars across connected calendar accounts.

    Returns a list of calendars with their IDs, names, colors, and permissions.
    Use this to discover available calendars before listing events.

    Returns:
        Dictionary with 'calendars' key containing list of calendar objects.
    """
    client = get_client()
    calendars = await client.list_calendars()

    return {
        "calendars": [_format_calendar(cal) for cal in calendars],
        "count": len(calendars),
    }


@handle_tool_errors
async def update_calendar_metadata(
    calendar_id: str,
    busy: bool | None = None,
    override_color: str | None = None,
    override_name: str | None = None,
) -> dict:
    """Update Morgen-specific metadata for a calendar.

    This allows customizing how a calendar appears in Morgen without
    modifying the underlying calendar provider.

    Args:
        calendar_id: The virtual ID of the calendar to update.
        busy: Whether events from this calendar count toward availability.
        override_color: Custom color for the calendar (hex format, e.g., "#ff0000").
        override_name: Custom display name for the calendar.

    Returns:
        Dictionary indicating success or error.
    """
    if busy is None and override_color is None and override_name is None:
        return {
            "error": "At least one of busy, override_color, or override_name must be provided.",
        }

    if override_color is not None:
        validate_hex_color(override_color)

    # Resolve virtual calendar ID and extract account ID
    real_calendar_id = resolve_id(calendar_id)
    real_account_id = extract_account_from_calendar(real_calendar_id)

    client = get_client()
    await client.update_calendar_metadata(
        calendar_id=real_calendar_id,
        account_id=real_account_id,
        busy=busy,
        override_color=override_color,
        override_name=override_name,
    )

    return {
        "success": True,
        "message": "Calendar metadata updated successfully.",
        "updated": {
            "calendarId": calendar_id,
            "busy": busy,
            "overrideColor": override_color,
            "overrideName": override_name,
        },
    }
