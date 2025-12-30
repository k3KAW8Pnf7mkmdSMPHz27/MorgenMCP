"""Unit tests for Morgen API client."""

import pytest
import httpx
import respx

from morgenmcp.client import MorgenClient, get_client, set_client
from morgenmcp.models import (
    EventCreateRequest,
    EventDeleteRequest,
    EventUpdateRequest,
    MorgenAPIError,
)


@pytest.fixture
def mock_client():
    """Create a client with a mock API key."""
    return MorgenClient(api_key="test_api_key_123")


@pytest.fixture
def reset_global_client():
    """Reset global client after tests."""
    yield
    # Reset by setting to None indirectly
    import morgenmcp.client
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


@respx.mock
class TestCalendarEndpoints:
    """Tests for calendar API endpoints."""

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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


@respx.mock
class TestEventEndpoints:
    """Tests for event API endpoints."""

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_create_event_success(self):
        """Test successful event creation."""
        respx.post("https://api.morgen.so/v3/events/create").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "id": "new_evt_123",
                        "calendarId": "cal456",
                        "accountId": "acc789",
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

        assert response.id == "new_evt_123"
        assert response.calendar_id == "cal456"

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self):
        """Test that context manager properly closes the client."""
        async with MorgenClient(api_key="test_key") as client:
            # Access the internal client to create it
            _ = client.client
            assert client._client is not None

        # After exiting context, client should be closed
        assert client._client is None

    @pytest.mark.asyncio
    async def test_context_manager_returns_client(self):
        """Test that context manager returns the client."""
        async with MorgenClient(api_key="test_key") as client:
            assert isinstance(client, MorgenClient)
