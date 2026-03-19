"""Async HTTP client for Morgen API."""

import logging
import os
import time
from typing import Any

import httpx

from morgenmcp.models import (
    Account,
    AccountsListResponse,
    APIResponse,
    Calendar,
    CalendarsListResponse,
    CalendarUpdateRequest,
    Event,
    EventCreateRequest,
    EventCreateResponse,
    EventDeleteRequest,
    EventsListResponse,
    EventUpdateRequest,
    MorgenAPIError,
    RateLimitInfo,
    Tag,
    Task,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskMoveRequest,
    TasksListResponse,
    TaskUpdateRequest,
)

logger = logging.getLogger(__name__)


class _CacheEntry:
    """A cached response with timestamp."""

    __slots__ = ("data", "timestamp")

    def __init__(self, data: Any, timestamp: float):
        self.data = data
        self.timestamp = timestamp


class MorgenClient:
    """Async client for interacting with the Morgen API."""

    BASE_URL = "https://api.morgen.so/v3"
    TASK_CACHE_TTL = 300.0  # 5 minutes

    def __init__(self, api_key: str | None = None):
        """Initialize the Morgen client.

        Args:
            api_key: Morgen API key. If not provided, reads from MORGEN_API_KEY env var.
        """
        self.api_key = api_key or os.environ.get("MORGEN_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Morgen API key is required. "
                "Pass it directly or set MORGEN_API_KEY environment variable."
            )
        self._client: httpx.AsyncClient | None = None
        self._task_cache: dict[str, _CacheEntry] = {}

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "Authorization": f"ApiKey {self.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> MorgenClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Async context manager exit."""
        await self.close()

    def _parse_rate_limit_headers(
        self, response: httpx.Response
    ) -> RateLimitInfo | None:
        """Parse rate limit information from response headers."""
        try:
            limit = response.headers.get("RateLimit-Limit")
            remaining = response.headers.get("RateLimit-Remaining")
            reset = response.headers.get("RateLimit-Reset")

            if limit and remaining and reset:
                return RateLimitInfo(
                    limit=int(limit),
                    remaining=int(remaining),
                    reset_seconds=int(reset),
                )
        except ValueError, TypeError:
            pass
        return None

    def _handle_error(self, response: httpx.Response) -> None:
        """Handle API error responses."""
        rate_limit_info = self._parse_rate_limit_headers(response)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise MorgenAPIError(
                f"Rate limit exceeded. Retry after {retry_after} seconds.",
                status_code=429,
                rate_limit_info=rate_limit_info,
            )

        if response.status_code == 401:
            raise MorgenAPIError(
                "Authentication failed. Check your API key.",
                status_code=401,
                rate_limit_info=rate_limit_info,
            )

        if response.status_code == 403:
            raise MorgenAPIError(
                "Access forbidden. You may not have permission for this operation.",
                status_code=403,
                rate_limit_info=rate_limit_info,
            )

        if response.status_code >= 400:
            try:
                error_data = response.json()
                message = error_data.get("message", response.text)
            except Exception:
                message = response.text

            raise MorgenAPIError(
                f"API error: {message}",
                status_code=response.status_code,
                rate_limit_info=rate_limit_info,
            )

    # Cache helpers

    def _task_cache_key(self, updated_after: str | None) -> str:
        """Build a cache key for list_tasks."""
        return f"list_tasks:{updated_after or ''}"

    def _get_cached_tasks(self, key: str) -> _CacheEntry | None:
        """Return a cache entry if it exists and is not expired."""
        entry = self._task_cache.get(key)
        if entry and (time.monotonic() - entry.timestamp) < self.TASK_CACHE_TTL:
            return entry
        return None

    def _get_stale_cached_tasks(self, key: str) -> _CacheEntry | None:
        """Return a cache entry even if expired (for 429 fallback)."""
        return self._task_cache.get(key)

    def _set_cached_tasks(self, key: str, data: Any) -> None:
        """Store a response in the task cache."""
        self._task_cache[key] = _CacheEntry(data=data, timestamp=time.monotonic())

    def invalidate_task_cache(self) -> None:
        """Clear all task cache entries. Called after any task write operation."""
        if self._task_cache:
            logger.debug("Invalidating task cache (%d entries)", len(self._task_cache))
        self._task_cache.clear()

    # Account endpoints

    async def list_accounts(self) -> list[Account]:
        """List all connected calendar accounts.

        Returns:
            List of Account objects.
        """
        response = await self.client.get("/integrations/accounts/list")
        self._handle_error(response)

        data = response.json()
        api_response = APIResponse[AccountsListResponse].model_validate(data)
        return api_response.data.accounts

    # Calendar endpoints

    async def list_calendars(self) -> list[Calendar]:
        """List all calendars across connected accounts.

        Returns:
            List of Calendar objects.
        """
        response = await self.client.get("/calendars/list")
        self._handle_error(response)

        data = response.json()
        api_response = APIResponse[CalendarsListResponse].model_validate(data)
        return api_response.data.calendars

    async def update_calendar_metadata(
        self,
        calendar_id: str,
        account_id: str,
        busy: bool | None = None,
        override_color: str | None = None,
        override_name: str | None = None,
    ) -> None:
        """Update Morgen-specific calendar metadata.

        Args:
            calendar_id: The ID of the calendar to update.
            account_id: The ID of the account the calendar belongs to.
            busy: Whether the calendar is considered for availability.
            override_color: Custom color override (hex format).
            override_name: Custom name override.
        """
        from morgenmcp.models import CalendarMetadata

        metadata = CalendarMetadata(
            busy=busy,
            override_color=override_color,
            override_name=override_name,
        )

        request = CalendarUpdateRequest(
            id=calendar_id,
            account_id=account_id,
            metadata=metadata,
        )

        response = await self.client.post(
            "/calendars/update",
            json=request.model_dump(by_alias=True, exclude_none=True),
        )
        self._handle_error(response)

    # Event endpoints

    async def list_events(
        self,
        account_id: str,
        calendar_ids: list[str],
        start: str,
        end: str,
    ) -> list[Event]:
        """List events in a time window.

        Args:
            account_id: The calendar account ID.
            calendar_ids: List of calendar IDs to retrieve events from.
            start: Start of time window in ISO 8601 format.
            end: End of time window in ISO 8601 format.

        Returns:
            List of Event objects.
        """
        params = {
            "accountId": account_id,
            "calendarIds": ",".join(calendar_ids),
            "start": start,
            "end": end,
        }

        response = await self.client.get("/events/list", params=params)
        self._handle_error(response)

        data = response.json()
        api_response = APIResponse[EventsListResponse].model_validate(data)
        return api_response.data.events

    async def create_event(self, request: EventCreateRequest) -> EventCreateResponse:
        """Create a new calendar event.

        Args:
            request: Event creation request with all event details.

        Returns:
            EventCreateResponse with the new event's ID.
        """
        response = await self.client.post(
            "/events/create",
            json=request.model_dump(by_alias=True, exclude_none=True),
        )
        self._handle_error(response)

        data = response.json()
        return APIResponse[EventCreateResponse].model_validate(data).data

    async def update_event(
        self,
        request: EventUpdateRequest,
        series_update_mode: str = "single",
    ) -> None:
        """Update an existing event.

        Args:
            request: Event update request with fields to update.
            series_update_mode: How to handle recurring events.
                - "single": Update this event only (default)
                - "future": Update this and future occurrences
                - "all": Update all events in the series
        """
        params = {"seriesUpdateMode": series_update_mode}

        response = await self.client.post(
            "/events/update",
            params=params,
            json=request.model_dump(by_alias=True, exclude_none=True),
        )
        self._handle_error(response)

    async def delete_event(
        self,
        request: EventDeleteRequest,
        series_update_mode: str = "single",
    ) -> None:
        """Delete an event.

        Args:
            request: Event delete request with event identification.
            series_update_mode: How to handle recurring events.
                - "single": Delete this event only (default)
                - "future": Delete this and future occurrences
                - "all": Delete all events in the series
        """
        params = {"seriesUpdateMode": series_update_mode}

        response = await self.client.post(
            "/events/delete",
            params=params,
            json=request.model_dump(by_alias=True, exclude_none=True),
        )
        self._handle_error(response)

    # Task endpoints

    async def list_tasks(
        self,
        limit: int = 100,
        updated_after: str | None = None,
    ) -> TasksListResponse:
        """List tasks with optional filters. Uses in-memory cache (5min TTL).

        Returns:
            TasksListResponse containing tasks list plus spaces/labelDefs metadata.

        Raises:
            MorgenAPIError: On API errors. For 429s, falls back to stale cache
                if available (caller receives data with no error).
        """
        cache_key = self._task_cache_key(updated_after)

        # Check fresh cache first
        cached = self._get_cached_tasks(cache_key)
        if cached:
            logger.debug("Task cache hit (key=%s)", cache_key)
            return cached.data

        params: dict[str, Any] = {}
        if limit != 100:
            params["limit"] = str(limit)
        if updated_after:
            params["updatedAfter"] = updated_after

        try:
            response = await self.client.get("/tasks/list", params=params)
            self._handle_error(response)
        except MorgenAPIError as e:
            if e.status_code == 429:
                stale = self._get_stale_cached_tasks(cache_key)
                if stale:
                    logger.info(
                        "Rate limited on list_tasks, returning stale cache (age=%.0fs)",
                        time.monotonic() - stale.timestamp,
                    )
                    return stale.data
            raise

        data = response.json()
        api_response = APIResponse[TasksListResponse].model_validate(data)
        result = api_response.data

        self._set_cached_tasks(cache_key, result)
        logger.debug(
            "Task cache stored (key=%s, tasks=%d)", cache_key, len(result.tasks)
        )
        return result

    async def get_task(self, task_id: str) -> Task:
        """Get a single task by ID."""
        response = await self.client.get("/tasks", params={"id": task_id})
        self._handle_error(response)
        data = response.json()
        return Task.model_validate(data["data"]["task"])

    async def create_task(self, request: TaskCreateRequest) -> TaskCreateResponse:
        """Create a new task."""
        response = await self.client.post(
            "/tasks/create",
            json=request.model_dump(by_alias=True, exclude_none=True),
        )
        self._handle_error(response)
        self.invalidate_task_cache()
        data = response.json()
        return APIResponse[TaskCreateResponse].model_validate(data).data

    async def update_task(self, request: TaskUpdateRequest) -> None:
        """Update a task. Returns 204 No Content."""
        response = await self.client.post(
            "/tasks/update",
            json=request.model_dump(by_alias=True, exclude_none=True),
        )
        self._handle_error(response)
        self.invalidate_task_cache()

    async def move_task(self, request: TaskMoveRequest) -> None:
        """Move/reorder a task. Returns 204 No Content."""
        response = await self.client.post(
            "/tasks/move",
            json=request.model_dump(by_alias=True, exclude_none=True),
        )
        self._handle_error(response)
        self.invalidate_task_cache()

    async def delete_task(self, task_id: str) -> None:
        """Delete a task. Returns 204 No Content."""
        response = await self.client.post(
            "/tasks/delete",
            json={"id": task_id},
        )
        self._handle_error(response)
        self.invalidate_task_cache()

    async def close_task(
        self, task_id: str, occurrence_start: str | None = None
    ) -> None:
        """Mark task completed. Returns 204 No Content."""
        body: dict[str, Any] = {"id": task_id}
        if occurrence_start:
            body["occurrenceStart"] = occurrence_start
        response = await self.client.post("/tasks/close", json=body)
        self._handle_error(response)
        self.invalidate_task_cache()

    async def reopen_task(
        self, task_id: str, occurrence_start: str | None = None
    ) -> None:
        """Reopen completed task. Returns 204 No Content."""
        body: dict[str, Any] = {"id": task_id}
        if occurrence_start:
            body["occurrenceStart"] = occurrence_start
        response = await self.client.post("/tasks/reopen", json=body)
        self._handle_error(response)
        self.invalidate_task_cache()

    # Tag endpoints

    async def list_tags(self, updated_after: str | None = None) -> list[Tag]:
        """List all tags."""
        params: dict[str, str] = {}
        if updated_after:
            params["updatedAfter"] = updated_after
        response = await self.client.get("/tags/list", params=params)
        self._handle_error(response)
        data = response.json()
        if isinstance(data, list):
            return [Tag.model_validate(t) for t in data]
        elif "data" in data:
            return [Tag.model_validate(t) for t in data["data"]]
        return []

    async def get_tag(self, tag_id: str) -> Tag:
        """Get a single tag."""
        response = await self.client.get("/tags", params={"id": tag_id})
        self._handle_error(response)
        return Tag.model_validate(response.json())

    async def create_tag(self, name: str, color: str | None = None) -> Tag:
        """Create a new tag."""
        body: dict[str, Any] = {"name": name}
        if color:
            body["color"] = color
        response = await self.client.post("/tags/create", json=body)
        self._handle_error(response)
        return Tag.model_validate(response.json())

    async def update_tag(
        self, tag_id: str, name: str | None = None, color: str | None = None
    ) -> None:
        """Update a tag. Returns 204 No Content."""
        body: dict[str, Any] = {"id": tag_id}
        if name is not None:
            body["name"] = name
        if color is not None:
            body["color"] = color
        response = await self.client.post("/tags/update", json=body)
        self._handle_error(response)

    async def delete_tag(self, tag_id: str) -> None:
        """Delete a tag (soft delete). Returns 204 No Content."""
        response = await self.client.post("/tags/delete", json={"id": tag_id})
        self._handle_error(response)


# Global client instance for use in tools
_client: MorgenClient | None = None


def get_client() -> MorgenClient:
    """Get or create the global Morgen client instance."""
    global _client
    if _client is None:
        _client = MorgenClient()
    return _client


def set_client(client: MorgenClient) -> None:
    """Set the global Morgen client instance (useful for testing)."""
    global _client
    _client = client
