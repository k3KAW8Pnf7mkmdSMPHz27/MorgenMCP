"""FastMCP server for Morgen calendar API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from morgenmcp.tools.accounts import list_accounts
from morgenmcp.tools.calendars import list_calendars, update_calendar_metadata
from morgenmcp.tools.events import (
    batch_delete_events,
    batch_update_events,
    create_event,
    delete_event,
    list_events,
    update_event,
)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize and clean up the Morgen HTTP client."""
    from morgenmcp.client import get_client

    try:
        yield
    finally:
        client = get_client()
        await client.close()


# Create the MCP server
mcp = FastMCP(
    "morgen-calendar",
    lifespan=lifespan,
    instructions="""
    Morgen Calendar MCP Server provides access to Morgen's unified calendar API.

    All IDs are 7-character virtual IDs (e.g., "aB-9xZ_") for token efficiency.

    Workflow:
    1. Use list_calendars to discover available calendars
    2. Use list_events with calendar_ids to get events (compact=True for fewer tokens)
    3. Use update_event or delete_event with just event_id
    4. Use batch_delete_events or batch_update_events for bulk operations

    Simplified signatures:
    - create_event: just calendar_id (account derived automatically)
    - update_event/delete_event: just event_id (account/calendar derived automatically)
    - list_events: optional calendar_ids (queries all if omitted)

    Important notes:
    - Times are in LocalDateTime format (e.g., "2023-03-01T10:15:00") with separate timeZone
    - Durations use ISO 8601 format (e.g., "PT1H" for 1 hour, "PT30M" for 30 minutes)
    - For recurring events, use seriesUpdateMode to control how updates affect the series
    """,
)

# Register tools with annotations and tags
mcp.tool(
    name="morgen_list_accounts",
    tags={"accounts", "read"},
    timeout=30.0,
    annotations={
        "title": "List Accounts",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)(list_accounts)
mcp.tool(
    name="morgen_list_calendars",
    tags={"calendars", "read"},
    timeout=30.0,
    annotations={
        "title": "List Calendars",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)(list_calendars)
mcp.tool(
    name="morgen_update_calendar_metadata",
    tags={"calendars", "write"},
    timeout=30.0,
    annotations={
        "title": "Update Calendar Metadata",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)(update_calendar_metadata)
mcp.tool(
    name="morgen_list_events",
    tags={"events", "read"},
    timeout=120.0,
    annotations={
        "title": "List Events",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)(list_events)
mcp.tool(
    name="morgen_create_event",
    tags={"events", "write"},
    timeout=30.0,
    annotations={
        "title": "Create Event",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    },
)(create_event)
mcp.tool(
    name="morgen_update_event",
    tags={"events", "write"},
    timeout=30.0,
    annotations={
        "title": "Update Event",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)(update_event)
mcp.tool(
    name="morgen_delete_event",
    tags={"events", "delete"},
    timeout=30.0,
    annotations={
        "title": "Delete Event",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": True,
    },
)(delete_event)
mcp.tool(
    name="morgen_batch_delete_events",
    tags={"events", "delete", "batch"},
    timeout=120.0,
    annotations={
        "title": "Batch Delete Events",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": True,
    },
)(batch_delete_events)
mcp.tool(
    name="morgen_batch_update_events",
    tags={"events", "write", "batch"},
    timeout=120.0,
    annotations={
        "title": "Batch Update Events",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)(batch_update_events)


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
