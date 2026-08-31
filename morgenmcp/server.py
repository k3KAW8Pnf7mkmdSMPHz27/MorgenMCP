"""FastMCP server for Morgen calendar API."""

import argparse
import asyncio
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.middleware.caching import (
    CallToolSettings,
    ListPromptsSettings,
    ListResourcesSettings,
    ListToolsSettings,
    ReadResourceSettings,
    ResponseCachingMiddleware,
)
from fastmcp.utilities.logging import get_logger
from mcp.types import ToolAnnotations

from morgenmcp import __version__
from morgenmcp.client import (
    TAGS_LIMIT_ENV,
    TAGS_MAX_LIMIT,
    TASKS_LIMIT_ENV,
    TASKS_MAX_LIMIT,
    resolve_limit,
    set_limit_override,
    validate_limit,
)
from morgenmcp.resources import (
    res_account,
    res_accounts,
    res_calendar,
    res_calendar_events,
    res_calendars,
    res_events_this_week,
    res_events_today,
    res_events_upcoming,
    res_server,
    res_tags,
    res_tasks,
    res_tasks_today,
)
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
from morgenmcp.tools.id_registry import HASH_SCHEME_VERSION
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


def _require_api_key() -> None:
    """Fail fast when MORGEN_API_KEY is missing.

    Without this, a misconfigured server starts cleanly, advertises all 22
    tools, and only errors on the first tool call — a confusing lazy failure.
    """
    if not os.environ.get("MORGEN_API_KEY", "").strip():
        raise RuntimeError(
            "MORGEN_API_KEY is not set. Export it (e.g. via .envrc) "
            "before starting morgenmcp."
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

    _require_api_key()

    # Initialize persistent ID store
    try:
        from key_value.aio.stores.filetree import FileTreeStore

        data_dir = _get_data_dir() / _ID_STORE_DIR
        store = FileTreeStore(
            data_directory=data_dir,
            default_collection=_ID_COLLECTION,
        )
        await store.setup()
        # Persisted entries hold raw Morgen IDs, which base64-decode to
        # calendar email addresses — keep the directory owner-only.
        os.chmod(data_dir, 0o700)
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
    version=__version__,
    lifespan=lifespan,
    on_duplicate="error",
    instructions=f"""
    Morgen Calendar MCP Server provides access to Morgen's unified calendar,
    task, and tag API.

    All IDs are 7-character virtual IDs (e.g., "aB-9xZ_") for token efficiency.
    Virtual IDs are deterministic — see the morgen://server resource for the
    full hash contract (currently scheme version {HASH_SCHEME_VERSION}). A
    bump in scheme_version means every previously-issued virtual ID is now
    stale; re-list before using saved IDs.

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
    - Recurring events: pass recurrence_rules=[{{"frequency":"weekly","interval":1,"by_day":["mo"]}}]
    """,
)

# Register tools with annotations and tags
mcp.tool(
    name="morgen_list_accounts",
    tags={"accounts", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="List Accounts",
        readOnlyHint=True,
        openWorldHint=True,
    ),
)(list_accounts)
mcp.tool(
    name="morgen_list_calendars",
    tags={"calendars", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="List Calendars",
        readOnlyHint=True,
        openWorldHint=True,
    ),
)(list_calendars)
mcp.tool(
    name="morgen_update_calendar_metadata",
    tags={"calendars", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Update Calendar Metadata",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)(update_calendar_metadata)
mcp.tool(
    name="morgen_list_events",
    tags={"events", "read"},
    timeout=120.0,
    annotations=ToolAnnotations(
        title="List Events",
        readOnlyHint=True,
        openWorldHint=True,
    ),
)(list_events)
mcp.tool(
    name="morgen_create_event",
    tags={"events", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Create Event",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    ),
)(create_event)
mcp.tool(
    name="morgen_update_event",
    tags={"events", "write"},
    timeout=60.0,
    annotations=ToolAnnotations(
        title="Update Event",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)(update_event)
mcp.tool(
    name="morgen_delete_event",
    tags={"events", "delete"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Delete Event",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    ),
)(delete_event)
mcp.tool(
    name="morgen_batch_delete_events",
    tags={"events", "delete", "batch"},
    timeout=120.0,
    annotations=ToolAnnotations(
        title="Batch Delete Events",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    ),
)(batch_delete_events)
mcp.tool(
    name="morgen_batch_update_events",
    tags={"events", "write", "batch"},
    timeout=120.0,
    annotations=ToolAnnotations(
        title="Batch Update Events",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    ),
)(batch_update_events)

# Task tools
mcp.tool(
    name="morgen_list_tasks",
    tags={"tasks", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="List Tasks",
        readOnlyHint=True,
        openWorldHint=True,
    ),
)(list_tasks)
mcp.tool(
    name="morgen_get_task",
    tags={"tasks", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Get Task",
        readOnlyHint=True,
        openWorldHint=True,
    ),
)(get_task)
mcp.tool(
    name="morgen_create_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Create Task",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    ),
)(create_task)
mcp.tool(
    name="morgen_update_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Update Task",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)(update_task)
mcp.tool(
    name="morgen_move_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Move Task",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)(move_task)
mcp.tool(
    name="morgen_complete_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Complete Task",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)(complete_task)
mcp.tool(
    name="morgen_reopen_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Reopen Task",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)(reopen_task)
mcp.tool(
    name="morgen_delete_task",
    tags={"tasks", "delete"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Delete Task",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    ),
)(delete_task)
mcp.tool(
    name="morgen_batch_delete_tasks",
    tags={"tasks", "delete", "batch"},
    timeout=120.0,
    annotations=ToolAnnotations(
        title="Batch Delete Tasks",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    ),
)(batch_delete_tasks)

# Tag tools
mcp.tool(
    name="morgen_list_tags",
    tags={"tags", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="List Tags",
        readOnlyHint=True,
        openWorldHint=True,
    ),
)(list_tags)
mcp.tool(
    name="morgen_create_tag",
    tags={"tags", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Create Tag",
        readOnlyHint=False,
        destructiveHint=False,
        openWorldHint=True,
    ),
)(create_tag)
mcp.tool(
    name="morgen_update_tag",
    tags={"tags", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Update Tag",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    ),
)(update_tag)
mcp.tool(
    name="morgen_delete_tag",
    tags={"tags", "delete"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Delete Tag",
        readOnlyHint=False,
        destructiveHint=True,
        openWorldHint=True,
    ),
)(delete_tag)


# MCP resources — read-only data clients can fetch without invoking tools
_RESOURCE_ANNOTATIONS = {"readOnlyHint": True, "idempotentHint": True}

mcp.resource(
    "morgen://server",
    mime_type="application/json",
    tags={"server", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_server)
mcp.resource(
    "morgen://accounts",
    mime_type="application/json",
    tags={"accounts", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_accounts)
mcp.resource(
    "morgen://account/{account_id}",
    mime_type="application/json",
    tags={"accounts", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_account)
mcp.resource(
    "morgen://calendars",
    mime_type="application/json",
    tags={"calendars", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_calendars)
mcp.resource(
    "morgen://calendar/{calendar_id}",
    mime_type="application/json",
    tags={"calendars", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_calendar)
mcp.resource(
    "morgen://calendar/{calendar_id}/events",
    mime_type="application/json",
    tags={"calendars", "events", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_calendar_events)
mcp.resource(
    "morgen://events/today",
    mime_type="application/json",
    tags={"events", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_events_today)
mcp.resource(
    "morgen://events/this-week",
    mime_type="application/json",
    tags={"events", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_events_this_week)
mcp.resource(
    "morgen://events/upcoming",
    mime_type="application/json",
    tags={"events", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_events_upcoming)
mcp.resource(
    "morgen://tasks",
    mime_type="application/json",
    tags={"tasks", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_tasks)
mcp.resource(
    "morgen://tasks/today",
    mime_type="application/json",
    tags={"tasks", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_tasks_today)
mcp.resource(
    "morgen://tags",
    mime_type="application/json",
    tags={"tags", "read"},
    annotations=_RESOURCE_ANNOTATIONS,
)(res_tags)


# Response caching for read-only tools and all resources.
#
# Allowlist-only on tools — writes (create/update/delete/complete/reopen/move)
# MUST never be cached: same args returning a cached "success" silently turns
# duplicate writes into no-ops. The list below is conservative; everything not
# listed bypasses the cache.
#
# 60s TTL is short enough that a write the user just made appears almost
# immediately, and long enough to dedupe rapid repeat reads inside one
# conversation. Storage is in-memory (FastMCP default) — disk persistence
# would let stale "events/today" survive a server restart, which is worse
# than re-fetching.
_CACHEABLE_READ_TOOLS = [
    "morgen_list_accounts",
    "morgen_list_calendars",
    "morgen_list_events",
    "morgen_list_tasks",
    "morgen_get_task",
    "morgen_list_tags",
]
_CACHE_TTL_S = 60

# Listing caches are explicitly DISABLED. ResponseCachingMiddleware defaults to
# caching tools/list, resources/list, and prompts/list with a 5-minute TTL — but
# listing is a pure in-memory component enumeration (no Morgen API call), so the
# cache saves no latency and only risks serving a stale set. Critically, read-only
# mode (`_apply_read_only`) toggles tool visibility via `mcp.disable(...)`; a cached
# tools/list would mask that change for up to 5 minutes. We cache only the reads
# that actually hit the network (`call_tool` on the allowlist, and `read_resource`).
_DISABLED = {"enabled": False}

mcp.add_middleware(
    ResponseCachingMiddleware(
        call_tool_settings=CallToolSettings(
            included_tools=_CACHEABLE_READ_TOOLS,
            ttl=_CACHE_TTL_S,
        ),
        read_resource_settings=ReadResourceSettings(
            enabled=True,
            ttl=_CACHE_TTL_S,
        ),
        list_tools_settings=ListToolsSettings(**_DISABLED),
        list_resources_settings=ListResourcesSettings(**_DISABLED),
        list_prompts_settings=ListPromptsSettings(**_DISABLED),
    )
)


# Tools that only read state stay available in read-only mode; everything tagged
# "write" or "delete" is disabled. Every mutating tool carries one of these tags
# (verified by the tag-taxonomy tests), so this is a complete gate.
_MUTATING_TAGS = {"write", "delete"}

_TRUTHY_ENV = {"1", "true", "yes", "on"}


def _read_only_requested(cli_read_only: bool = False) -> bool:
    """Return whether read-only mode is enabled via the CLI flag or env var.

    Either the ``--read-only`` flag or a truthy ``MORGENMCP_READ_ONLY`` env var
    (``1``/``true``/``yes``/``on``, case-insensitive) enables the mode.
    """
    if cli_read_only:
        return True
    env_val = os.environ.get("MORGENMCP_READ_ONLY", "").strip().lower()
    return env_val in _TRUTHY_ENV


def _apply_limit_config(
    cli_tasks_limit: int | None = None,
    cli_tags_limit: int | None = None,
) -> None:
    """Validate and register the configured per-endpoint list limits.

    Both the CLI values and any env vars are range-checked here so a bad value
    surfaces as a clean argparse error at startup rather than as a confusing
    under-count on the first list call.
    """
    for value, flag, env_name, maximum in (
        (cli_tasks_limit, "--tasks-limit", TASKS_LIMIT_ENV, TASKS_MAX_LIMIT),
        (cli_tags_limit, "--tags-limit", TAGS_LIMIT_ENV, TAGS_MAX_LIMIT),
    ):
        if value is not None:
            validate_limit(value, flag, maximum)
        set_limit_override(env_name, value)
        # Range-check the env var too, so a bad one also fails at startup
        # rather than on the first list call.
        resolve_limit(None, env_name, None, maximum)


def _apply_read_only(server: FastMCP) -> None:
    """Disable all mutating (write/delete) tools on the server in place.

    Applied once at startup, before ``mcp.run()`` — never mid-session — so the
    disabled state is baked into the very first ``list_tools`` response and the
    response cache never serves a pre-disable (full) tool list.
    """
    server.disable(tags=_MUTATING_TAGS)
    logger.info("read-only mode: mutating tools (write/delete) disabled")


def main() -> None:
    """Run the MCP server."""
    parser = argparse.ArgumentParser(
        prog="morgenmcp",
        description="Morgen calendar MCP server.",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help=(
            "Disable all mutating (create/update/delete) tools; only read tools "
            "are exposed. Also enabled via MORGENMCP_READ_ONLY=1."
        ),
    )
    parser.add_argument(
        "--tasks-limit",
        type=int,
        metavar="N",
        help=(
            "Default `limit` sent to /tasks/list when a caller does not specify "
            "one (1-100). Also settable via MORGENMCP_TASKS_LIMIT; the flag wins. "
            "Defaults to 100, Morgen's documented default."
        ),
    )
    parser.add_argument(
        "--tags-limit",
        type=int,
        metavar="N",
        help=(
            "Default `limit` sent to /tags/list when a caller does not specify "
            "one. Also settable via MORGENMCP_TAGS_LIMIT; the flag wins. Unset "
            "omits the parameter, which returns all tags."
        ),
    )
    args = parser.parse_args()

    try:
        _require_api_key()
    except RuntimeError as e:
        parser.error(str(e))  # clean CLI message instead of a lifespan traceback

    try:
        _apply_limit_config(
            cli_tasks_limit=args.tasks_limit, cli_tags_limit=args.tags_limit
        )
    except ValueError as e:
        parser.error(str(e))  # bad limit fails at startup, not on first call

    if _read_only_requested(cli_read_only=args.read_only):
        _apply_read_only(mcp)

    mcp.run()


if __name__ == "__main__":
    main()
