"""MCP tools for Morgen calendar operations."""

from morgenmcp.client import get_client
from morgenmcp.tools.utils import handle_tool_errors
from morgenmcp.validators import validate_hex_color


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
        "calendars": [
            {
                "id": cal.id,
                "accountId": cal.account_id,
                "integrationId": cal.integration_id,
                "name": cal.name,
                "color": cal.color,
                "sortOrder": cal.sort_order,
                "permissions": {
                    "canRead": cal.my_rights.may_read_items if cal.my_rights else False,
                    "canWrite": cal.my_rights.may_write_all if cal.my_rights else False,
                    "canDelete": cal.my_rights.may_delete if cal.my_rights else False,
                }
                if cal.my_rights
                else None,
                "metadata": {
                    "busy": cal.metadata.busy if cal.metadata else None,
                    "overrideColor": cal.metadata.override_color if cal.metadata else None,
                    "overrideName": cal.metadata.override_name if cal.metadata else None,
                }
                if cal.metadata
                else None,
            }
            for cal in calendars
        ],
        "count": len(calendars),
    }


@handle_tool_errors
async def update_calendar_metadata(
    calendar_id: str,
    account_id: str,
    busy: bool | None = None,
    override_color: str | None = None,
    override_name: str | None = None,
) -> dict:
    """Update Morgen-specific metadata for a calendar.

    This allows customizing how a calendar appears in Morgen without
    modifying the underlying calendar provider.

    Args:
        calendar_id: The ID of the calendar to update.
        account_id: The ID of the account the calendar belongs to.
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

    client = get_client()
    await client.update_calendar_metadata(
        calendar_id=calendar_id,
        account_id=account_id,
        busy=busy,
        override_color=override_color,
        override_name=override_name,
    )

    return {
        "success": True,
        "message": "Calendar metadata updated successfully.",
        "updated": {
            "calendarId": calendar_id,
            "accountId": account_id,
            "busy": busy,
            "overrideColor": override_color,
            "overrideName": override_name,
        },
    }
