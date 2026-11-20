"""Unofficial FastMCP server for the Morgen calendar API."""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, SupportsFloat

from fastmcp import FastMCP
from fastmcp.resources.base import ResourceResult
from fastmcp.server.middleware.caching import (
    CallToolSettings,
    ListPromptsSettings,
    ListResourcesSettings,
    ListToolsSettings,
    ReadResourceSettings,
    ResponseCachingMiddleware,
)
from fastmcp.server.middleware.middleware import CallNext, MiddlewareContext
from fastmcp.tools.base import ToolResult
from fastmcp.utilities.logging import get_logger
from key_value.aio.stores.memory import MemoryStore
from mcp.types import (
    CallToolRequestParams,
    ReadResourceRequestParams,
    ToolAnnotations,
)

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
from morgenmcp.tools.tags import (
    create_tag,
    delete_tag,
    get_tag,
    list_tags,
    update_tag,
)
from morgenmcp.tools.tasks import (
    batch_delete_tasks,
    complete_task,
    create_task,
    delete_task,
    get_task,
    list_task_lists,
    list_tasks,
    move_task,
    reopen_task,
    update_task,
)
from morgenmcp.tools.utils import _ACTIVE_CACHE_CONTROL, ResponseCacheControl

logger = get_logger(__name__)

_ID_STORE_DIR = "id_store"
_ID_COLLECTION = "id_mappings"
_HEARTBEAT_INTERVAL_S = (
    300.0  # 5 minutes — long enough not to spam, short enough to detect wedges
)


def _require_api_key() -> None:
    """Fail fast when MORGEN_API_KEY is missing.

    Without this, a misconfigured server starts cleanly, advertises its full
    tool set, and only errors on the first tool call — a confusing lazy failure.
    """
    if not os.environ.get("MORGEN_API_KEY", "").strip():
        raise RuntimeError(
            "MORGEN_API_KEY is not set. Set it in your MCP client's env "
            "block, or export it before starting morgenmcp."
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
    Unofficial Morgen Calendar MCP Server provides access to Morgen's unified calendar,
    task, and tag API.

    All IDs are 7-character virtual IDs (e.g., "aB-9xZ_") for token efficiency.
    Virtual IDs are deterministic — see the morgen://server resource for the
    full hash contract (currently scheme version {HASH_SCHEME_VERSION}). A
    bump in scheme_version means every previously-issued virtual ID is now
    stale; re-list before using saved IDs.

    Calendar workflow:
    1. Use list_calendars to discover available calendars
    2. Use list_events with calendar_ids to get events (compact=True for fewer
       tokens). A compact line may carry a kind tag inside the ID brackets,
       e.g. "[abc123 task]": task, routine (a check-off-able Morgen Routine),
       flexible (Morgen auto-scheduled, so movable), free, or a comma-joined
       pair such as "[abc123 task,free]" (no space). No tag means an ordinary
       busy commitment. Treat task/routine/flexible blocks as movable and free
       ones as informational, not as hard scheduling conflicts. Parse the tag
       by matching the trailing [<id> <tag>] at end of line, never by scanning
       for braces: an event TITLE may itself contain braces or brackets.
    3. Use update_event or delete_event with just event_id. Deleting a
       single event that is already gone succeeds with alreadyGone=True;
       with series_update_mode future/all it is an error, as other
       occurrences may remain.
    4. Use batch_delete_events or batch_update_events for bulk operations

    Task workflow:
    1. Use list_tasks to enumerate tasks (set limit; results may be truncated)
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
        read_only_hint=True,
        open_world_hint=True,
    ),
)(list_accounts)
mcp.tool(
    name="morgen_list_calendars",
    tags={"calendars", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="List Calendars",
        read_only_hint=True,
        open_world_hint=True,
    ),
)(list_calendars)
mcp.tool(
    name="morgen_update_calendar_metadata",
    tags={"calendars", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Update Calendar Metadata",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)(update_calendar_metadata)
mcp.tool(
    name="morgen_list_events",
    tags={"events", "read"},
    timeout=120.0,
    annotations=ToolAnnotations(
        title="List Events",
        read_only_hint=True,
        open_world_hint=True,
    ),
)(list_events)
mcp.tool(
    name="morgen_create_event",
    tags={"events", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Create Event",
        read_only_hint=False,
        destructive_hint=False,
        open_world_hint=True,
    ),
)(create_event)
mcp.tool(
    name="morgen_update_event",
    tags={"events", "write"},
    timeout=60.0,
    annotations=ToolAnnotations(
        title="Update Event",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)(update_event)
mcp.tool(
    name="morgen_delete_event",
    tags={"events", "delete"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Delete Event",
        read_only_hint=False,
        destructive_hint=True,
        open_world_hint=True,
    ),
)(delete_event)
mcp.tool(
    name="morgen_batch_delete_events",
    tags={"events", "delete", "batch"},
    timeout=120.0,
    annotations=ToolAnnotations(
        title="Batch Delete Events",
        read_only_hint=False,
        destructive_hint=True,
        open_world_hint=True,
    ),
)(batch_delete_events)
mcp.tool(
    name="morgen_batch_update_events",
    tags={"events", "write", "batch"},
    timeout=120.0,
    annotations=ToolAnnotations(
        title="Batch Update Events",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    ),
)(batch_update_events)

# Task tools
mcp.tool(
    name="morgen_list_task_lists",
    tags={"tasks", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="List Task Lists",
        read_only_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)(list_task_lists)
mcp.tool(
    name="morgen_list_tasks",
    tags={"tasks", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="List Tasks",
        read_only_hint=True,
        open_world_hint=True,
    ),
)(list_tasks)
mcp.tool(
    name="morgen_get_task",
    tags={"tasks", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Get Task",
        read_only_hint=True,
        open_world_hint=True,
    ),
)(get_task)
mcp.tool(
    name="morgen_create_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Create Task",
        read_only_hint=False,
        destructive_hint=False,
        open_world_hint=True,
    ),
)(create_task)
mcp.tool(
    name="morgen_update_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Update Task",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)(update_task)
mcp.tool(
    name="morgen_move_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Move Task",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)(move_task)
mcp.tool(
    name="morgen_complete_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Complete Task",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)(complete_task)
mcp.tool(
    name="morgen_reopen_task",
    tags={"tasks", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Reopen Task",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)(reopen_task)
mcp.tool(
    name="morgen_delete_task",
    tags={"tasks", "delete"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Delete Task",
        read_only_hint=False,
        destructive_hint=True,
        open_world_hint=True,
    ),
)(delete_task)
mcp.tool(
    name="morgen_batch_delete_tasks",
    tags={"tasks", "delete", "batch"},
    timeout=120.0,
    annotations=ToolAnnotations(
        title="Batch Delete Tasks",
        read_only_hint=False,
        destructive_hint=True,
        open_world_hint=True,
    ),
)(batch_delete_tasks)

# Tag tools
mcp.tool(
    name="morgen_list_tags",
    tags={"tags", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="List Tags",
        read_only_hint=True,
        open_world_hint=True,
    ),
)(list_tags)
mcp.tool(
    name="morgen_get_tag",
    tags={"tags", "read"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Get Tag",
        read_only_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)(get_tag)
mcp.tool(
    name="morgen_create_tag",
    tags={"tags", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Create Tag",
        read_only_hint=False,
        destructive_hint=False,
        open_world_hint=True,
    ),
)(create_tag)
mcp.tool(
    name="morgen_update_tag",
    tags={"tags", "write"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Update Tag",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    ),
)(update_tag)
mcp.tool(
    name="morgen_delete_tag",
    tags={"tags", "delete"},
    timeout=30.0,
    annotations=ToolAnnotations(
        title="Delete Tag",
        read_only_hint=False,
        destructive_hint=True,
        open_world_hint=True,
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
# duplicate writes into no-ops. The single-item reads `morgen_get_task` and
# `morgen_get_tag` are also excluded: they cost 1 point each (vs. 10 for a
# `/list` call), and they are what callers use for read-after-write
# verification (e.g. `"deleted": True` after `delete_task`, a 404 after
# `delete_tag`), so they must never serve stale state — including changes made
# outside this server, which write invalidation cannot see. The list below is
# conservative; everything not listed bypasses the cache.
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
    "morgen_list_task_lists",
    "morgen_list_tasks",
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

_ACTIVE_CACHE_TARGET: ContextVar[tuple[str, str] | None] = ContextVar(
    "_ACTIVE_CACHE_TARGET", default=None
)
_ACTIVE_COMMIT_GUARD: ContextVar[Callable[[], bool] | None] = ContextVar(
    "_ACTIVE_COMMIT_GUARD", default=None
)


@dataclass(frozen=True)
class _CacheDomain:
    """Groups write tools with the read tools and resource URIs they invalidate."""

    name: str
    write_tools: frozenset[str]
    read_tools: tuple[str, ...]
    resource_pred: Callable[[str], bool]


_DEFAULT_CACHE_DOMAINS: tuple[_CacheDomain, ...] = (
    _CacheDomain(
        name="events",
        write_tools=frozenset(
            {
                "morgen_create_event",
                "morgen_update_event",
                "morgen_delete_event",
                "morgen_batch_delete_events",
                "morgen_batch_update_events",
            }
        ),
        read_tools=("morgen_list_events",),
        resource_pred=lambda u: (
            u.startswith("morgen://events/")
            or (u.startswith("morgen://calendar/") and u.endswith("/events"))
        ),
    ),
    _CacheDomain(
        name="calendars",
        write_tools=frozenset({"morgen_update_calendar_metadata"}),
        read_tools=("morgen_list_calendars",),
        resource_pred=lambda u: (
            u == "morgen://calendars"
            or (u.startswith("morgen://calendar/") and not u.endswith("/events"))
        ),
    ),
    _CacheDomain(
        name="tasks",
        write_tools=frozenset(
            {
                "morgen_create_task",
                "morgen_update_task",
                "morgen_move_task",
                "morgen_complete_task",
                "morgen_reopen_task",
                "morgen_delete_task",
                "morgen_batch_delete_tasks",
            }
        ),
        read_tools=("morgen_list_tasks", "morgen_list_task_lists"),
        resource_pred=lambda u: u.startswith("morgen://tasks"),
    ),
    _CacheDomain(
        name="tags",
        write_tools=frozenset(
            {"morgen_create_tag", "morgen_update_tag", "morgen_delete_tag"}
        ),
        read_tools=("morgen_list_tags",),
        resource_pred=lambda u: u == "morgen://tags",
    ),
)


class _TrackedMemoryStore(MemoryStore):
    """In-memory store that indexes cached keys by tool name or resource URI."""

    def __init__(self) -> None:
        super().__init__()
        self._tracked_keys: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)

    def _prune_expired(self, now: float) -> None:
        empty_targets: list[tuple[str, str]] = []
        for target, keys in self._tracked_keys.items():
            for key in [k for k, exp in keys.items() if exp <= now]:
                del keys[key]
            if not keys:
                empty_targets.append(target)
        for target in empty_targets:
            del self._tracked_keys[target]

    async def put(
        self,
        key: str,
        value: Mapping[str, Any],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        commit_guard = _ACTIVE_COMMIT_GUARD.get()
        if commit_guard is not None and not commit_guard():
            return
        await super().put(key, value, collection=collection, ttl=ttl)
        if commit_guard is not None and not commit_guard():
            await self.delete(key=key, collection=collection)
            return
        now = time.monotonic()
        self._prune_expired(now)
        target = _ACTIVE_CACHE_TARGET.get()
        if target is not None and collection == target[0]:
            expires_at = now + float(ttl) if ttl is not None else float("inf")
            self._tracked_keys[target][key] = expires_at

    async def invalidate_tools(self, tool_names: tuple[str, ...]) -> None:
        now = time.monotonic()
        self._prune_expired(now)
        for name in tool_names:
            for key in self._tracked_keys.pop(("tools/call", name), {}):
                await self.delete(key=key, collection="tools/call")

    async def invalidate_resources(self, predicate: Callable[[str], bool]) -> None:
        now = time.monotonic()
        self._prune_expired(now)
        uris = [
            uri
            for col, uri in self._tracked_keys
            if col == "resources/read" and predicate(uri)
        ]
        for uri in uris:
            for key in self._tracked_keys.pop(("resources/read", uri), {}):
                await self.delete(key=key, collection="resources/read")


class _WriteInvalidatingCachingMiddleware(ResponseCachingMiddleware):
    """ResponseCachingMiddleware that owns mutation dependencies, per-domain
    generations, and incomplete-response skipping.
    """

    def __init__(
        self,
        *,
        domains: tuple[_CacheDomain, ...] = _DEFAULT_CACHE_DOMAINS,
        **kwargs: Any,
    ) -> None:
        self._tracked_store = _TrackedMemoryStore()
        self._domains = domains
        self._generations: dict[str, int] = {domain.name: 0 for domain in domains}
        super().__init__(cache_storage=self._tracked_store, **kwargs)

    def _domain_for_write(self, tool_name: str) -> _CacheDomain | None:
        for domain in self._domains:
            if tool_name in domain.write_tools:
                return domain
        return None

    def _domain_for_read_tool(self, tool_name: str) -> _CacheDomain | None:
        for domain in self._domains:
            if tool_name in domain.read_tools:
                return domain
        return None

    def _domain_for_resource(self, uri: str) -> _CacheDomain | None:
        for domain in self._domains:
            if domain.resource_pred(uri):
                return domain
        return None

    async def _invalidate_domain(self, domain: _CacheDomain) -> None:
        self._generations[domain.name] += 1
        await self._tracked_store.invalidate_tools(domain.read_tools)
        await self._tracked_store.invalidate_resources(domain.resource_pred)

    def _make_commit_guard(
        self, domain: _CacheDomain | None, control: ResponseCacheControl
    ) -> Callable[[], bool]:
        if domain is None:
            return lambda: control.cacheable
        start_gen = self._generations[domain.name]
        domain_name = domain.name
        return lambda: control.cacheable and self._generations[domain_name] == start_gen

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        if (write_domain := self._domain_for_write(tool_name)) is not None:
            self._generations[write_domain.name] += 1
            try:
                return await call_next(context)
            finally:
                await self._invalidate_domain(write_domain)

        read_domain = self._domain_for_read_tool(tool_name)
        control = ResponseCacheControl()
        guard = self._make_commit_guard(read_domain, control)
        target_tok = _ACTIVE_CACHE_TARGET.set(("tools/call", tool_name))
        ctrl_tok = _ACTIVE_CACHE_CONTROL.set(control)
        guard_tok = _ACTIVE_COMMIT_GUARD.set(guard)
        try:
            return await super().on_call_tool(context, call_next)
        finally:
            _ACTIVE_COMMIT_GUARD.reset(guard_tok)
            _ACTIVE_CACHE_CONTROL.reset(ctrl_tok)
            _ACTIVE_CACHE_TARGET.reset(target_tok)

    async def on_read_resource(
        self,
        context: MiddlewareContext[ReadResourceRequestParams],
        call_next: CallNext[ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        uri = str(context.message.uri)
        read_domain = self._domain_for_resource(uri)
        control = ResponseCacheControl()
        guard = self._make_commit_guard(read_domain, control)
        target_tok = _ACTIVE_CACHE_TARGET.set(("resources/read", uri))
        ctrl_tok = _ACTIVE_CACHE_CONTROL.set(control)
        guard_tok = _ACTIVE_COMMIT_GUARD.set(guard)
        try:
            return await super().on_read_resource(context, call_next)
        finally:
            _ACTIVE_COMMIT_GUARD.reset(guard_tok)
            _ACTIVE_CACHE_CONTROL.reset(ctrl_tok)
            _ACTIVE_CACHE_TARGET.reset(target_tok)


mcp.add_middleware(
    _WriteInvalidatingCachingMiddleware(
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
            "Defaults to 100; Morgen's own default is 1."
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
