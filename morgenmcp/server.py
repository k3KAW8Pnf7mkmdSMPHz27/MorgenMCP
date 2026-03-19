"""FastMCP server for Morgen calendar API."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

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
from morgenmcp.tools.tags import (
    create_tag,
    delete_tag,
    get_tag,
    list_tags,
    update_tag,
)
from morgenmcp.tools.tasks import (
    close_task,
    create_task,
    delete_task,
    get_task,
    list_tasks,
    move_task,
    reopen_task,
    update_task,
)

logger = logging.getLogger(__name__)

_ID_STORE_DIR = "id_store"
_ID_COLLECTION = "id_mappings"


def _get_data_dir() -> Path:
    """Return the data directory for persistent storage."""
    env_dir = os.environ.get("MORGENMCP_DATA_DIR")
    if env_dir:
        return Path(env_dir)

    import platformdirs

    return Path(platformdirs.user_data_dir("morgenmcp"))


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize and clean up the Morgen HTTP client and persistent ID store."""
    from morgenmcp.client import get_client
    from morgenmcp.tools.id_registry import load_from_store, set_store

    # Initialize persistent ID store
    try:
        from key_value.aio.stores.filetree import FileTreeStore

        data_dir = _get_data_dir() / _ID_STORE_DIR
        store = FileTreeStore(
            data_directory=data_dir,
            default_collection=_ID_COLLECTION,
        )
        await store.setup()
        set_store(store)
        count = await load_from_store(data_dir, _ID_COLLECTION)
        if count:
            logger.info("Loaded %d persisted ID mappings", count)
    except Exception:
        logger.warning(
            "Failed to initialize persistent ID store, continuing without persistence",
            exc_info=True,
        )
        set_store(None)

    try:
        yield
    finally:
        set_store(None)
        client = get_client()
        await client.close()


# Create the MCP server
mcp = FastMCP(
    "morgen-calendar",
    lifespan=lifespan,
    instructions="""
    Morgen Calendar & Tasks MCP Server provides access to Morgen's unified calendar and task API.

    All IDs are 7-character virtual IDs (e.g., "aB-9xZ_") for token efficiency.

    Calendar Workflow:
    1. Use list_calendars to discover available calendars
    2. Use list_events with calendar_ids to get events (compact=True for fewer tokens)
    3. Use update_event or delete_event with just event_id
    4. Use batch_delete_events or batch_update_events for bulk operations

    Task Workflow:
    1. Use list_tasks to get all tasks (compact=True for fewer tokens)
    2. Use create_task to add tasks; use parent_task_id for subtasks
    3. Use close_task/reopen_task to toggle completion
    4. Use move_task to reorder or reparent tasks

    Tag Workflow:
    1. Use list_tags to see available tags
    2. Use create_tag to define new tags with name and color
    3. Assign tags to tasks via the 'tags' parameter (list of tag UUIDs)

    Important notes:
    - Times are in LocalDateTime format (e.g., "2023-03-01T10:15:00") with separate timeZone
    - Durations use ISO 8601 format (e.g., "PT1H" for 1 hour, "PT30M" for 30 minutes)
    - list_tasks costs 10 rate limit points per request
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

# Task tools
mcp.tool(
    name="morgen_list_tasks",
    tags={"tasks", "read"},
    timeout=60.0,
    annotations={
        "title": "List Tasks",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)(list_tasks)
mcp.tool(
    name="morgen_get_task",
    tags={"tasks", "read"},
    timeout=30.0,
    annotations={
        "title": "Get Task",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)(get_task)
mcp.tool(
    name="morgen_create_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations={
        "title": "Create Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    },
)(create_task)
mcp.tool(
    name="morgen_update_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations={
        "title": "Update Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)(update_task)
mcp.tool(
    name="morgen_move_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations={
        "title": "Move Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    },
)(move_task)
mcp.tool(
    name="morgen_delete_task",
    tags={"tasks", "delete"},
    timeout=30.0,
    annotations={
        "title": "Delete Task",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": True,
    },
)(delete_task)
mcp.tool(
    name="morgen_close_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations={
        "title": "Close Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)(close_task)
mcp.tool(
    name="morgen_reopen_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations={
        "title": "Reopen Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)(reopen_task)

# Tag tools
mcp.tool(
    name="morgen_list_tags",
    tags={"tags", "read"},
    timeout=30.0,
    annotations={
        "title": "List Tags",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)(list_tags)
mcp.tool(
    name="morgen_get_tag",
    tags={"tags", "read"},
    timeout=30.0,
    annotations={
        "title": "Get Tag",
        "readOnlyHint": True,
        "openWorldHint": True,
    },
)(get_tag)
mcp.tool(
    name="morgen_create_tag",
    tags={"tags", "write"},
    timeout=30.0,
    annotations={
        "title": "Create Tag",
        "readOnlyHint": False,
        "destructiveHint": False,
        "openWorldHint": True,
    },
)(create_tag)
mcp.tool(
    name="morgen_update_tag",
    tags={"tags", "write"},
    timeout=30.0,
    annotations={
        "title": "Update Tag",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)(update_tag)
mcp.tool(
    name="morgen_delete_tag",
    tags={"tags", "delete"},
    timeout=30.0,
    annotations={
        "title": "Delete Tag",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": True,
    },
)(delete_tag)


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
