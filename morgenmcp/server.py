"""FastMCP server for Morgen calendar API."""

import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.utilities.logging import get_logger

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
from morgenmcp.tools.tags import create_tag, delete_tag, list_tags, update_tag
from morgenmcp.tools.tasks import (
    batch_delete_tasks,
    complete_task,
    create_task,
    delete_task,
    get_task,
    list_tasks,
    move_task,
    reopen_task,
    update_task,
)

logger = get_logger(__name__)

_ID_STORE_DIR = "id_store"
_ID_COLLECTION = "id_mappings"
_HEARTBEAT_INTERVAL_S = (
    300.0  # 5 minutes — long enough not to spam, short enough to detect wedges
)


def _get_data_dir() -> Path:
    """Return the data directory for persistent storage."""
    env_dir = os.environ.get("MORGENMCP_DATA_DIR")
    if env_dir:
        return Path(env_dir)

    import platformdirs

    return Path(platformdirs.user_data_dir("morgenmcp"))


async def _heartbeat(started_at: float) -> None:
    """Periodically log liveness so a wedged event loop is detectable in logs.

    Why: when Claude Desktop's stdio pipe to the server gets stuck, the process
    looks alive (PID present, RAM stable) but no requests arrive. A heartbeat
    that *does* keep firing means the loop is healthy and the wedge is in the
    transport; a heartbeat that *stops* means the loop itself is stuck.
    """
    while True:
        try:
            await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
            uptime_s = int(time.monotonic() - started_at)
            logger.info("heartbeat uptime=%ds", uptime_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("heartbeat error (continuing)")


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize and clean up the Morgen HTTP client and persistent ID store."""
    from morgenmcp.client import get_client
    from morgenmcp.tools.id_registry import flush_pending, load_from_store, set_store

    started_at = time.monotonic()
    logger.info("morgenmcp lifespan starting")

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
        logger.info("ID store ready (%d persisted mappings loaded)", count)
    except Exception:
        logger.warning(
            "Failed to initialize persistent ID store, continuing without persistence",
            exc_info=True,
        )
        set_store(None)

    heartbeat_task = asyncio.create_task(
        _heartbeat(started_at), name="morgenmcp-heartbeat"
    )
    logger.info("morgenmcp ready (heartbeat every %ds)", int(_HEARTBEAT_INTERVAL_S))

    try:
        yield
    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task
        try:
            await flush_pending()
        except Exception:
            logger.warning(
                "Error flushing pending ID writes on shutdown", exc_info=True
            )
        set_store(None)
        client = get_client()
        await client.close()
        logger.info("morgenmcp lifespan stopped")


# Create the MCP server
mcp = FastMCP(
    "morgen-calendar",
    lifespan=lifespan,
    instructions="""
    Morgen Calendar MCP Server provides access to Morgen's unified calendar,
    task, and tag API.

    All IDs are 7-character virtual IDs (e.g., "aB-9xZ_") for token efficiency.

    Calendar workflow:
    1. Use list_calendars to discover available calendars
    2. Use list_events with calendar_ids to get events (compact=True for fewer tokens)
    3. Use update_event or delete_event with just event_id
    4. Use batch_delete_events or batch_update_events for bulk operations

    Task workflow:
    1. Use list_tasks to enumerate tasks (paginate via limit + updated_after)
    2. Use create_task / update_task / delete_task for CRUD
    3. Use complete_task / reopen_task to toggle completion
    4. Use move_task to reorder or change a task's parent

    Tag workflow:
    1. Use list_tags to enumerate user tags
    2. Use create_tag / update_tag / delete_tag for CRUD
    3. Pass tag virtual IDs to create_task or update_task via tag_ids

    Simplified signatures:
    - create_event: just calendar_id (account derived automatically)
    - update_event/delete_event: just event_id (account/calendar derived automatically)
    - list_events: optional calendar_ids (queries all if omitted)

    Important notes:
    - Times are in LocalDateTime format (e.g., "2023-03-01T10:15:00") with separate timeZone
    - Durations use ISO 8601 format (e.g., "PT1H" for 1 hour, "PT30M" for 30 minutes)
    - Alert offsets are negative durations (e.g., "-PT15M" = 15 min before)
    - For recurring events, use seriesUpdateMode to control how updates affect the series
    - Recurring events: pass recurrence_rules=[{"frequency":"weekly","interval":1,"by_day":["mo"]}]
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
    timeout=60.0,
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
    timeout=30.0,
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
        "idempotentHint": True,
        "openWorldHint": True,
    },
)(move_task)
mcp.tool(
    name="morgen_complete_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations={
        "title": "Complete Task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)(complete_task)
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
    name="morgen_batch_delete_tasks",
    tags={"tasks", "delete", "batch"},
    timeout=120.0,
    annotations={
        "title": "Batch Delete Tasks",
        "readOnlyHint": False,
        "destructiveHint": True,
        "openWorldHint": True,
    },
)(batch_delete_tasks)

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
