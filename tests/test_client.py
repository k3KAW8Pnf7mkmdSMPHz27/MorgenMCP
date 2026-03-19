"""Unit tests for Morgen API client."""

import httpx
import pytest
import respx

from morgenmcp.client import MorgenClient, get_client, set_client
from morgenmcp.models import (
    EventCreateRequest,
    EventDeleteRequest,
    EventUpdateRequest,
    MorgenAPIError,
    TaskCreateRequest,
    TaskMoveRequest,
    TaskUpdateRequest,
)


@pytest.fixture
def mock_client():
    """Create a client with a mock API key."""
    return MorgenClient(api_key="test_api_key_123")


@pytest.fixture
def reset_global_client():
    """Reset global client before and after tests."""
    import morgenmcp.client

    morgenmcp.client._client = None
    yield
    morgenmcp.client._client = None


class TestClientInitialization:
    """Tests for client initialization."""

    def test_client_init_with_api_key(self):
        """Test client initialization with explicit API key."""
        client = MorgenClient(api_key="my_api_key")
        assert client.api_key == "my_api_key"

    def test_client_init_from_env(self, monkeypatch):
        """Test client initialization from environment variable."""
        monkeypatch.setenv("MORGEN_API_KEY", "env_api_key")
        client = MorgenClient()
        assert client.api_key == "env_api_key"

    def test_client_init_missing_key(self, monkeypatch):
        """Test client raises error when API key is missing."""
        monkeypatch.delenv("MORGEN_API_KEY", raising=False)
        with pytest.raises(ValueError, match="Morgen API key is required"):
            MorgenClient()

    def test_client_headers(self, mock_client):
        """Test that client sets correct headers."""
        client = mock_client.client
        assert "Authorization" in client.headers
        assert client.headers["Authorization"] == "ApiKey test_api_key_123"
        assert client.headers["Accept"] == "application/json"


class TestClientRateLimitHandling:
    """Tests for rate limit header parsing."""

    def test_parse_rate_limit_headers(self, mock_client):
        """Test parsing rate limit headers from response."""
        response = httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "250",
                "RateLimit-Remaining": "100",
                "RateLimit-Reset": "459",
            },
        )
        info = mock_client._parse_rate_limit_headers(response)

        assert info is not None
        assert info.limit == 250
        assert info.remaining == 100
        assert info.reset_seconds == 459

    def test_parse_rate_limit_headers_missing(self, mock_client):
        """Test parsing when rate limit headers are missing."""
        response = httpx.Response(200)
        info = mock_client._parse_rate_limit_headers(response)

        assert info is None

    def test_parse_rate_limit_headers_invalid(self, mock_client):
        """Test parsing when rate limit headers are invalid."""
        response = httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "not_a_number",
                "RateLimit-Remaining": "100",
                "RateLimit-Reset": "459",
            },
        )
        info = mock_client._parse_rate_limit_headers(response)

        assert info is None

    def test_parse_rate_limit_headers_partial_present(self, mock_client):
        """Test parsing when only some rate limit headers are present (returns None)."""
        response = httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "250",
                # Missing Remaining and Reset
            },
        )
        info = mock_client._parse_rate_limit_headers(response)

        assert info is None

    def test_parse_rate_limit_headers_all_non_numeric(self, mock_client):
        """Test parsing when all rate limit headers are non-numeric (ValueError)."""
        response = httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "abc",
                "RateLimit-Remaining": "def",
                "RateLimit-Reset": "ghi",
            },
        )
        info = mock_client._parse_rate_limit_headers(response)

        assert info is None

    def test_parse_rate_limit_headers_float_values(self, mock_client):
        """Test parsing when rate limit headers contain float values (ValueError)."""
        response = httpx.Response(
            200,
            headers={
                "RateLimit-Limit": "250.5",
                "RateLimit-Remaining": "100",
                "RateLimit-Reset": "459",
            },
        )
        info = mock_client._parse_rate_limit_headers(response)

        assert info is None


class TestClientErrorHandling:
    """Tests for error handling."""

    def test_handle_rate_limit_error(self, mock_client):
        """Test handling 429 rate limit response."""
        response = httpx.Response(
            429,
            headers={
                "Retry-After": "300",
                "RateLimit-Limit": "250",
                "RateLimit-Remaining": "0",
                "RateLimit-Reset": "300",
            },
        )

        with pytest.raises(MorgenAPIError) as exc_info:
            mock_client._handle_error(response)

        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in str(exc_info.value)
        assert exc_info.value.rate_limit_info is not None

    def test_handle_auth_error(self, mock_client):
        """Test handling 401 authentication error."""
        response = httpx.Response(401)

        with pytest.raises(MorgenAPIError) as exc_info:
            mock_client._handle_error(response)

        assert exc_info.value.status_code == 401
        assert "Authentication failed" in str(exc_info.value)

    def test_handle_forbidden_error(self, mock_client):
        """Test handling 403 forbidden error."""
        response = httpx.Response(403)

        with pytest.raises(MorgenAPIError) as exc_info:
            mock_client._handle_error(response)

        assert exc_info.value.status_code == 403
        assert "Access forbidden" in str(exc_info.value)

    def test_handle_generic_error_with_json(self, mock_client):
        """Test handling generic error with JSON body."""
        response = httpx.Response(
            400,
            json={"message": "Invalid request parameters"},
        )

        with pytest.raises(MorgenAPIError) as exc_info:
            mock_client._handle_error(response)

        assert exc_info.value.status_code == 400
        assert "Invalid request parameters" in str(exc_info.value)

    def test_handle_generic_error_with_text(self, mock_client):
        """Test handling generic error with text body."""
        response = httpx.Response(500, text="Internal Server Error")

        with pytest.raises(MorgenAPIError) as exc_info:
            mock_client._handle_error(response)

        assert exc_info.value.status_code == 500

    def test_no_error_on_success(self, mock_client):
        """Test that no error is raised on success responses."""
        response = httpx.Response(200)
        # Should not raise
        mock_client._handle_error(response)

        response = httpx.Response(204)
        mock_client._handle_error(response)


class TestCalendarEndpoints:
    """Tests for calendar API endpoints."""

    @respx.mock
    async def test_list_calendars_success(self):
        """Test successful calendar listing."""
        respx.get("https://api.morgen.so/v3/calendars/list").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "calendars": [
                            {
                                "@type": "Calendar",
                                "id": "cal123",
                                "accountId": "acc456",
                                "integrationId": "google",
                                "name": "Work",
                            }
                        ]
                    }
                },
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            calendars = await client.list_calendars()

        assert len(calendars) == 1
        assert calendars[0].id == "cal123"
        assert calendars[0].name == "Work"

    @respx.mock
    async def test_list_calendars_empty(self):
        """Test calendar listing with no calendars."""
        respx.get("https://api.morgen.so/v3/calendars/list").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"calendars": []}},
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            calendars = await client.list_calendars()

        assert len(calendars) == 0

    @respx.mock
    async def test_update_calendar_metadata_success(self):
        """Test successful calendar metadata update."""
        respx.post("https://api.morgen.so/v3/calendars/update").mock(
            return_value=httpx.Response(200, json={"data": {}})
        )

        async with MorgenClient(api_key="test_key") as client:
            # Should not raise
            await client.update_calendar_metadata(
                calendar_id="cal123",
                account_id="acc456",
                busy=True,
                override_color="#ff0000",
            )


class TestEventEndpoints:
    """Tests for event API endpoints."""

    @respx.mock
    async def test_list_events_success(self):
        """Test successful event listing."""
        respx.get("https://api.morgen.so/v3/events/list").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "events": [
                            {
                                "@type": "Event",
                                "id": "evt123",
                                "calendarId": "cal456",
                                "accountId": "acc789",
                                "integrationId": "google",
                                "title": "Meeting",
                                "start": "2023-03-01T10:00:00",
                                "duration": "PT1H",
                            }
                        ]
                    }
                },
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            events = await client.list_events(
                account_id="acc789",
                calendar_ids=["cal456"],
                start="2023-03-01T00:00:00Z",
                end="2023-03-02T00:00:00Z",
            )

        assert len(events) == 1
        assert events[0].id == "evt123"
        assert events[0].title == "Meeting"

    @respx.mock
    async def test_list_events_query_params(self):
        """Test that list_events sends correct query parameters."""
        route = respx.get("https://api.morgen.so/v3/events/list").mock(
            return_value=httpx.Response(200, json={"data": {"events": []}})
        )

        async with MorgenClient(api_key="test_key") as client:
            await client.list_events(
                account_id="acc123",
                calendar_ids=["cal1", "cal2"],
                start="2023-03-01T00:00:00Z",
                end="2023-03-31T23:59:59Z",
            )

        # Check that request was made with correct params
        request = route.calls.last.request
        assert "accountId=acc123" in str(request.url)
        assert "calendarIds=cal1%2Ccal2" in str(request.url)  # URL encoded comma

    @respx.mock
    async def test_create_event_success(self):
        """Test successful event creation."""
        respx.post("https://api.morgen.so/v3/events/create").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "event": {
                            "id": "new_evt_123",
                            "calendarId": "cal456",
                            "accountId": "acc789",
                        }
                    }
                },
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            request = EventCreateRequest(
                account_id="acc789",
                calendar_id="cal456",
                title="New Meeting",
                start="2023-03-15T14:00:00",
                duration="PT1H",
                time_zone="Europe/Berlin",
                show_without_time=False,
            )
            response = await client.create_event(request)

        assert response.event.id == "new_evt_123"
        assert response.event.calendar_id == "cal456"

    @respx.mock
    async def test_update_event_success(self):
        """Test successful event update."""
        respx.post("https://api.morgen.so/v3/events/update").mock(
            return_value=httpx.Response(200, json={"data": {}})
        )

        async with MorgenClient(api_key="test_key") as client:
            request = EventUpdateRequest(
                id="evt123",
                account_id="acc456",
                calendar_id="cal789",
                title="Updated Meeting",
            )
            # Should not raise
            await client.update_event(request)

    @respx.mock
    async def test_update_event_series_mode(self):
        """Test event update with series update mode."""
        route = respx.post("https://api.morgen.so/v3/events/update").mock(
            return_value=httpx.Response(200, json={"data": {}})
        )

        async with MorgenClient(api_key="test_key") as client:
            request = EventUpdateRequest(
                id="evt123",
                account_id="acc456",
                calendar_id="cal789",
                title="Updated",
            )
            await client.update_event(request, series_update_mode="all")

        # Check query param
        request_made = route.calls.last.request
        assert "seriesUpdateMode=all" in str(request_made.url)

    @respx.mock
    async def test_delete_event_success(self):
        """Test successful event deletion."""
        respx.post("https://api.morgen.so/v3/events/delete").mock(
            return_value=httpx.Response(200, json={"data": {}})
        )

        async with MorgenClient(api_key="test_key") as client:
            request = EventDeleteRequest(
                id="evt123",
                account_id="acc456",
                calendar_id="cal789",
            )
            # Should not raise
            await client.delete_event(request)


class TestGlobalClient:
    """Tests for global client management."""

    def test_get_client_creates_instance(self, monkeypatch, reset_global_client):
        """Test that get_client creates a client instance."""
        monkeypatch.setenv("MORGEN_API_KEY", "test_key")
        client = get_client()
        assert client is not None
        assert client.api_key == "test_key"

    def test_get_client_returns_same_instance(self, monkeypatch, reset_global_client):
        """Test that get_client returns the same instance."""
        monkeypatch.setenv("MORGEN_API_KEY", "test_key")
        client1 = get_client()
        client2 = get_client()
        assert client1 is client2

    def test_set_client(self, reset_global_client):
        """Test that set_client overrides the global client."""
        custom_client = MorgenClient(api_key="custom_key")
        set_client(custom_client)

        retrieved = get_client()
        assert retrieved is custom_client
        assert retrieved.api_key == "custom_key"


class TestClientContextManager:
    """Tests for async context manager."""

    async def test_context_manager_closes_client(self):
        """Test that context manager properly closes the client."""
        async with MorgenClient(api_key="test_key") as client:
            # Access the internal client to create it
            _ = client.client
            assert client._client is not None

        # After exiting context, client should be closed
        assert client._client is None

    async def test_context_manager_returns_client(self):
        """Test that context manager returns the client."""
        async with MorgenClient(api_key="test_key") as client:
            assert isinstance(client, MorgenClient)


class TestTaskEndpoints:
    """Tests for task API endpoints."""

    @respx.mock
    async def test_list_tasks_success(self):
        """Test successful task listing."""
        respx.get("https://api.morgen.so/v3/tasks/list").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "tasks": [
                            {
                                "@type": "Task",
                                "id": "task123",
                                "title": "Review report",
                                "progress": "needs-action",
                            }
                        ],
                        "labelDefs": [],
                        "spaces": [],
                    }
                },
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            tasks = await client.list_tasks()

        assert len(tasks) == 1
        assert tasks[0].id == "task123"
        assert tasks[0].title == "Review report"

    @respx.mock
    async def test_list_tasks_with_params(self):
        """Test list_tasks sends correct query parameters."""
        route = respx.get("https://api.morgen.so/v3/tasks/list").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"tasks": [], "labelDefs": [], "spaces": []}},
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            await client.list_tasks(limit=50, updated_after="2023-01-01T00:00:00Z")

        request = route.calls.last.request
        assert "limit=50" in str(request.url)
        assert "updatedAfter=2023-01-01T00" in str(request.url)

    @respx.mock
    async def test_get_task_success(self):
        """Test getting a single task."""
        respx.get("https://api.morgen.so/v3/tasks").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "task": {
                            "@type": "Task",
                            "id": "task456",
                            "title": "Single task",
                        },
                        "labelDefs": [],
                    }
                },
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            task = await client.get_task("task456")

        assert task.id == "task456"
        assert task.title == "Single task"

    @respx.mock
    async def test_create_task_success(self):
        """Test successful task creation."""
        respx.post("https://api.morgen.so/v3/tasks/create").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"id": "new_task_123"}},
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            request = TaskCreateRequest(title="New task")
            response = await client.create_task(request)

        assert response.id == "new_task_123"

    @respx.mock
    async def test_create_task_sends_body(self):
        """Test that create_task sends correct request body."""
        route = respx.post("https://api.morgen.so/v3/tasks/create").mock(
            return_value=httpx.Response(200, json={"data": {"id": "t1"}})
        )

        async with MorgenClient(api_key="test_key") as client:
            request = TaskCreateRequest(
                title="Test",
                due="2023-03-15T17:00:00",
                time_zone="Europe/Berlin",
                priority=1,
                tags=["tag-uuid"],
            )
            await client.create_task(request)

        import json as json_mod
        body = json_mod.loads(route.calls.last.request.content)
        assert body["title"] == "Test"
        assert body["due"] == "2023-03-15T17:00:00"
        assert body["timeZone"] == "Europe/Berlin"
        assert body["priority"] == 1
        assert body["tags"] == ["tag-uuid"]

    @respx.mock
    async def test_update_task_success(self):
        """Test successful task update (204 No Content)."""
        respx.post("https://api.morgen.so/v3/tasks/update").mock(
            return_value=httpx.Response(204)
        )

        async with MorgenClient(api_key="test_key") as client:
            request = TaskUpdateRequest(id="task1", title="Updated")
            await client.update_task(request)

    @respx.mock
    async def test_move_task_success(self):
        """Test successful task move (204 No Content)."""
        respx.post("https://api.morgen.so/v3/tasks/move").mock(
            return_value=httpx.Response(204)
        )

        async with MorgenClient(api_key="test_key") as client:
            request = TaskMoveRequest(id="task1", previous_id="task0")
            await client.move_task(request)

    @respx.mock
    async def test_delete_task_success(self):
        """Test successful task deletion (204 No Content)."""
        respx.post("https://api.morgen.so/v3/tasks/delete").mock(
            return_value=httpx.Response(204)
        )

        async with MorgenClient(api_key="test_key") as client:
            await client.delete_task("task1")

    @respx.mock
    async def test_close_task_success(self):
        """Test marking task as completed (204 No Content)."""
        route = respx.post("https://api.morgen.so/v3/tasks/close").mock(
            return_value=httpx.Response(204)
        )

        async with MorgenClient(api_key="test_key") as client:
            await client.close_task("task1")

        import json as json_mod
        body = json_mod.loads(route.calls.last.request.content)
        assert body == {"id": "task1"}

    @respx.mock
    async def test_close_task_with_occurrence(self):
        """Test closing task with occurrence_start for recurring tasks."""
        route = respx.post("https://api.morgen.so/v3/tasks/close").mock(
            return_value=httpx.Response(204)
        )

        async with MorgenClient(api_key="test_key") as client:
            await client.close_task("task1", occurrence_start="2023-03-15T10:00:00")

        import json as json_mod
        body = json_mod.loads(route.calls.last.request.content)
        assert body["occurrenceStart"] == "2023-03-15T10:00:00"

    @respx.mock
    async def test_reopen_task_success(self):
        """Test reopening a completed task (204 No Content)."""
        respx.post("https://api.morgen.so/v3/tasks/reopen").mock(
            return_value=httpx.Response(204)
        )

        async with MorgenClient(api_key="test_key") as client:
            await client.reopen_task("task1")


class TestTagEndpoints:
    """Tests for tag API endpoints."""

    @respx.mock
    async def test_list_tags_direct_array(self):
        """Test list_tags when response is a direct JSON array (not wrapped)."""
        respx.get("https://api.morgen.so/v3/tags/list").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": "uuid1", "name": "Work", "color": "#A8D5BA"},
                    {"id": "uuid2", "name": "Personal", "color": "#FFD4B8"},
                ],
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            tags = await client.list_tags()

        assert len(tags) == 2
        assert tags[0].name == "Work"
        assert tags[1].color == "#FFD4B8"

    @respx.mock
    async def test_list_tags_wrapped_response(self):
        """Test list_tags when response is wrapped in data (defensive)."""
        respx.get("https://api.morgen.so/v3/tags/list").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "uuid1", "name": "Work"},
                    ]
                },
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            tags = await client.list_tags()

        assert len(tags) == 1
        assert tags[0].name == "Work"

    @respx.mock
    async def test_list_tags_with_updated_after(self):
        """Test list_tags sends updatedAfter param."""
        route = respx.get("https://api.morgen.so/v3/tags/list").mock(
            return_value=httpx.Response(200, json=[])
        )

        async with MorgenClient(api_key="test_key") as client:
            await client.list_tags(updated_after="2024-01-01T00:00:00Z")

        request = route.calls.last.request
        assert "updatedAfter=2024-01-01T00" in str(request.url)

    @respx.mock
    async def test_get_tag_success(self):
        """Test getting a single tag."""
        respx.get("https://api.morgen.so/v3/tags").mock(
            return_value=httpx.Response(
                200,
                json={"id": "uuid1", "name": "Work", "color": "#A8D5BA"},
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            tag = await client.get_tag("uuid1")

        assert tag.id == "uuid1"
        assert tag.name == "Work"

    @respx.mock
    async def test_create_tag_success(self):
        """Test successful tag creation."""
        respx.post("https://api.morgen.so/v3/tags/create").mock(
            return_value=httpx.Response(
                200,
                json={"id": "new-uuid", "name": "Personal", "color": "#FFD4B8"},
            )
        )

        async with MorgenClient(api_key="test_key") as client:
            tag = await client.create_tag(name="Personal", color="#FFD4B8")

        assert tag.id == "new-uuid"
        assert tag.name == "Personal"

    @respx.mock
    async def test_update_tag_success(self):
        """Test successful tag update (204 No Content)."""
        route = respx.post("https://api.morgen.so/v3/tags/update").mock(
            return_value=httpx.Response(204)
        )

        async with MorgenClient(api_key="test_key") as client:
            await client.update_tag(tag_id="uuid1", name="Updated", color="#B8D4FF")

        import json as json_mod
        body = json_mod.loads(route.calls.last.request.content)
        assert body["id"] == "uuid1"
        assert body["name"] == "Updated"
        assert body["color"] == "#B8D4FF"

    @respx.mock
    async def test_delete_tag_success(self):
        """Test successful tag deletion (204 No Content)."""
        route = respx.post("https://api.morgen.so/v3/tags/delete").mock(
            return_value=httpx.Response(204)
        )

        async with MorgenClient(api_key="test_key") as client:
            await client.delete_tag("uuid1")

        import json as json_mod
        body = json_mod.loads(route.calls.last.request.content)
        assert body == {"id": "uuid1"}
