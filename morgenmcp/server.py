"""FastMCP server for Morgen calendar API."""

from dotenv import load_dotenv

load_dotenv()  # Load .env from CWD if present

from fastmcp import FastMCP

from morgenmcp.tools.accounts import list_accounts
from morgenmcp.tools.calendars import list_calendars, update_calendar_metadata
from morgenmcp.tools.events import create_event, delete_event, list_events, update_event

# Create the MCP server
mcp = FastMCP(
    "morgen-calendar",
    instructions="""
    Morgen Calendar MCP Server provides access to Morgen's unified calendar API.

    Use list_accounts to see connected calendar accounts.
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

# Register tools directly - docstrings come from the tool functions
mcp.tool(name="morgen_list_accounts")(list_accounts)
mcp.tool(name="morgen_list_calendars")(list_calendars)
mcp.tool(name="morgen_update_calendar_metadata")(update_calendar_metadata)
mcp.tool(name="morgen_list_events")(list_events)
mcp.tool(name="morgen_create_event")(create_event)
mcp.tool(name="morgen_update_event")(update_event)
mcp.tool(name="morgen_delete_event")(delete_event)


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
