"""Unit tests for MCP tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from morgenmcp.models import (
    Calendar,
    CalendarMetadata,
    CalendarRights,
    Event,
    EventCreateResponse,
    EventDerived,
    Location,
    MorgenAPIError,
    Participant,
    ParticipantRoles,
    VirtualRoom,
)
from morgenmcp.tools.calendars import list_calendars, update_calendar_metadata
from morgenmcp.tools.events import create_event, delete_event, list_events, update_event


@pytest.fixture
def mock_morgen_client():
    """Create a mock Morgen client."""
    with patch("morgenmcp.tools.calendars.get_client") as cal_mock, \
         patch("morgenmcp.tools.events.get_client") as evt_mock:
        client = AsyncMock()
        cal_mock.return_value = client
        evt_mock.return_value = client
        yield client


@pytest.fixture
def sample_calendar():
    """Create a sample calendar for testing."""
    return Calendar(
        id="cal123",
        account_id="acc456",
        integration_id="google",
        name="Work Calendar",
        color="#4285f4",
        sort_order=0,
        my_rights=CalendarRights(
            may_read_free_busy=True,
            may_read_items=True,
            may_write_all=True,
            may_write_own=True,
            may_update_private=True,
            may_rsvp=True,
            may_admin=True,
            may_delete=True,
        ),
        metadata=CalendarMetadata(
            busy=True,
            override_color="#ff0000",
            override_name="My Work",
        ),
    )


@pytest.fixture
def sample_event():
    """Create a sample event for testing."""
    return Event(
        id="evt123",
        calendar_id="cal456",
        account_id="acc789",
        integration_id="google",
        title="Team Meeting",
        description="Weekly sync meeting",
        start="2023-03-01T10:00:00",
        duration="PT1H",
        time_zone="Europe/Berlin",
        show_without_time=False,
        free_busy_status="busy",
        privacy="public",
        locations={"1": Location(name="Conference Room A")},
        participants={
            "john@example.com": Participant(
                name="John Doe",
                email="john@example.com",
                roles=ParticipantRoles(attendee=True, owner=True),
                participation_status="accepted",
            ),
            "jane@example.com": Participant(
                name="Jane Smith",
                email="jane@example.com",
                roles=ParticipantRoles(attendee=True, owner=False),
                participation_status="needs-action",
            ),
        },
        derived=EventDerived(
            virtual_room=VirtualRoom(url="https://meet.google.com/abc-defg-hij")
        ),
    )


class TestListCalendars:
    """Tests for list_calendars tool."""

    @pytest.mark.asyncio
    async def test_list_calendars_success(self, mock_morgen_client, sample_calendar):
        """Test successful calendar listing."""
        mock_morgen_client.list_calendars.return_value = [sample_calendar]

        result = await list_calendars()

        assert "calendars" in result
        assert result["count"] == 1
        assert result["calendars"][0]["id"] == "cal123"
        assert result["calendars"][0]["name"] == "Work Calendar"
        assert result["calendars"][0]["permissions"]["canWrite"] is True

    @pytest.mark.asyncio
    async def test_list_calendars_empty(self, mock_morgen_client):
        """Test calendar listing with no calendars."""
        mock_morgen_client.list_calendars.return_value = []

        result = await list_calendars()

        assert result["calendars"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_calendars_api_error(self, mock_morgen_client):
        """Test calendar listing with API error."""
        mock_morgen_client.list_calendars.side_effect = MorgenAPIError(
            "Rate limit exceeded", status_code=429
        )

        result = await list_calendars()

        assert "error" in result
        assert result["status_code"] == 429

    @pytest.mark.asyncio
    async def test_list_calendars_with_no_metadata(self, mock_morgen_client):
        """Test calendar listing with calendar that has no metadata."""
        calendar = Calendar(
            id="cal123",
            account_id="acc456",
            integration_id="caldav",
        )
        mock_morgen_client.list_calendars.return_value = [calendar]

        result = await list_calendars()

        assert result["calendars"][0]["metadata"] is None
        assert result["calendars"][0]["permissions"] is None


class TestUpdateCalendarMetadata:
    """Tests for update_calendar_metadata tool."""

    @pytest.mark.asyncio
    async def test_update_calendar_metadata_success(self, mock_morgen_client):
        """Test successful calendar metadata update."""
        mock_morgen_client.update_calendar_metadata.return_value = None

        result = await update_calendar_metadata(
            calendar_id="cal123",
            account_id="acc456",
            busy=False,
            override_color="#00ff00",
        )

        assert result["success"] is True
        assert result["updated"]["calendarId"] == "cal123"
        assert result["updated"]["busy"] is False

    @pytest.mark.asyncio
    async def test_update_calendar_metadata_no_fields(self, mock_morgen_client):
        """Test update with no fields provided."""
        result = await update_calendar_metadata(
            calendar_id="cal123",
            account_id="acc456",
        )

        assert "error" in result
        assert "At least one" in result["error"]

    @pytest.mark.asyncio
    async def test_update_calendar_metadata_api_error(self, mock_morgen_client):
        """Test update with API error."""
        mock_morgen_client.update_calendar_metadata.side_effect = MorgenAPIError(
            "Calendar not found", status_code=404
        )

        result = await update_calendar_metadata(
            calendar_id="cal123",
            account_id="acc456",
            busy=True,
        )

        assert "error" in result
        assert result["status_code"] == 404


class TestListEvents:
    """Tests for list_events tool."""

    @pytest.mark.asyncio
    async def test_list_events_success(self, mock_morgen_client, sample_event):
        """Test successful event listing."""
        mock_morgen_client.list_events.return_value = [sample_event]

        result = await list_events(
            account_id="acc789",
            calendar_ids=["cal456"],
            start="2023-03-01T00:00:00Z",
            end="2023-03-02T00:00:00Z",
        )

        assert "events" in result
        assert result["count"] == 1
        assert result["events"][0]["id"] == "evt123"
        assert result["events"][0]["title"] == "Team Meeting"
        assert result["events"][0]["virtualRoomUrl"] == "https://meet.google.com/abc-defg-hij"
        assert len(result["events"][0]["participants"]) == 2

    @pytest.mark.asyncio
    async def test_list_events_empty(self, mock_morgen_client):
        """Test event listing with no events."""
        mock_morgen_client.list_events.return_value = []

        result = await list_events(
            account_id="acc789",
            calendar_ids=["cal456"],
            start="2023-03-01T00:00:00Z",
            end="2023-03-02T00:00:00Z",
        )

        assert result["events"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_events_api_error(self, mock_morgen_client):
        """Test event listing with API error."""
        mock_morgen_client.list_events.side_effect = MorgenAPIError(
            "Invalid date range", status_code=400
        )

        result = await list_events(
            account_id="acc789",
            calendar_ids=["cal456"],
            start="invalid",
            end="invalid",
        )

        assert "error" in result
        assert result["status_code"] == 400


class TestCreateEvent:
    """Tests for create_event tool."""

    @pytest.mark.asyncio
    async def test_create_event_success(self, mock_morgen_client):
        """Test successful event creation."""
        mock_morgen_client.create_event.return_value = EventCreateResponse(
            id="new_evt_123",
            calendar_id="cal456",
            account_id="acc789",
        )

        result = await create_event(
            account_id="acc789",
            calendar_id="cal456",
            title="New Meeting",
            start="2023-03-15T14:00:00",
            duration="PT1H",
            time_zone="Europe/Berlin",
        )

        assert result["success"] is True
        assert result["event"]["id"] == "new_evt_123"

    @pytest.mark.asyncio
    async def test_create_event_with_location(self, mock_morgen_client):
        """Test event creation with location."""
        mock_morgen_client.create_event.return_value = EventCreateResponse(
            id="new_evt_123",
            calendar_id="cal456",
            account_id="acc789",
        )

        result = await create_event(
            account_id="acc789",
            calendar_id="cal456",
            title="Office Meeting",
            start="2023-03-15T14:00:00",
            duration="PT1H",
            time_zone="Europe/Berlin",
            location="Conference Room B",
        )

        assert result["success"] is True
        # Verify the request was made with location
        call_args = mock_morgen_client.create_event.call_args
        request = call_args[0][0]
        assert request.locations is not None

    @pytest.mark.asyncio
    async def test_create_event_with_participants(self, mock_morgen_client):
        """Test event creation with participants."""
        mock_morgen_client.create_event.return_value = EventCreateResponse(
            id="new_evt_123",
            calendar_id="cal456",
            account_id="acc789",
        )

        result = await create_event(
            account_id="acc789",
            calendar_id="cal456",
            title="Team Sync",
            start="2023-03-15T14:00:00",
            duration="PT30M",
            time_zone="Europe/Berlin",
            participants=["alice@example.com", "bob@example.com"],
        )

        assert result["success"] is True
        # Verify participants were included
        call_args = mock_morgen_client.create_event.call_args
        request = call_args[0][0]
        assert request.participants is not None
        assert "alice@example.com" in request.participants

    @pytest.mark.asyncio
    async def test_create_event_api_error(self, mock_morgen_client):
        """Test event creation with API error."""
        mock_morgen_client.create_event.side_effect = MorgenAPIError(
            "Invalid duration format", status_code=400
        )

        result = await create_event(
            account_id="acc789",
            calendar_id="cal456",
            title="Bad Event",
            start="2023-03-15T14:00:00",
            duration="invalid",
            time_zone="Europe/Berlin",
        )

        assert "error" in result
        assert result["status_code"] == 400


class TestUpdateEvent:
    """Tests for update_event tool."""

    @pytest.mark.asyncio
    async def test_update_event_success(self, mock_morgen_client):
        """Test successful event update."""
        mock_morgen_client.update_event.return_value = None

        result = await update_event(
            event_id="evt123",
            account_id="acc456",
            calendar_id="cal789",
            title="Updated Title",
        )

        assert result["success"] is True
        assert result["eventId"] == "evt123"

    @pytest.mark.asyncio
    async def test_update_event_timing_fields_incomplete(self, mock_morgen_client):
        """Test update with incomplete timing fields."""
        result = await update_event(
            event_id="evt123",
            account_id="acc456",
            calendar_id="cal789",
            start="2023-03-15T14:00:00",
            # Missing duration, time_zone, is_all_day
        )

        assert "error" in result
        assert "all four must be provided" in result["error"]

    @pytest.mark.asyncio
    async def test_update_event_timing_fields_complete(self, mock_morgen_client):
        """Test update with complete timing fields."""
        mock_morgen_client.update_event.return_value = None

        result = await update_event(
            event_id="evt123",
            account_id="acc456",
            calendar_id="cal789",
            start="2023-03-15T14:00:00",
            duration="PT2H",
            time_zone="America/New_York",
            is_all_day=False,
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_event_series_mode(self, mock_morgen_client):
        """Test update with series update mode."""
        mock_morgen_client.update_event.return_value = None

        result = await update_event(
            event_id="evt123",
            account_id="acc456",
            calendar_id="cal789",
            title="Updated Recurring",
            series_update_mode="all",
        )

        assert result["success"] is True
        assert result["seriesUpdateMode"] == "all"
        mock_morgen_client.update_event.assert_called_once()
        call_kwargs = mock_morgen_client.update_event.call_args[1]
        assert call_kwargs["series_update_mode"] == "all"

    @pytest.mark.asyncio
    async def test_update_event_api_error(self, mock_morgen_client):
        """Test event update with API error."""
        mock_morgen_client.update_event.side_effect = MorgenAPIError(
            "Event not found", status_code=404
        )

        result = await update_event(
            event_id="nonexistent",
            account_id="acc456",
            calendar_id="cal789",
            title="Updated",
        )

        assert "error" in result
        assert result["status_code"] == 404


class TestDeleteEvent:
    """Tests for delete_event tool."""

    @pytest.mark.asyncio
    async def test_delete_event_success(self, mock_morgen_client):
        """Test successful event deletion."""
        mock_morgen_client.delete_event.return_value = None

        result = await delete_event(
            event_id="evt123",
            account_id="acc456",
            calendar_id="cal789",
        )

        assert result["success"] is True
        assert result["eventId"] == "evt123"

    @pytest.mark.asyncio
    async def test_delete_event_series_mode(self, mock_morgen_client):
        """Test deletion with series update mode."""
        mock_morgen_client.delete_event.return_value = None

        result = await delete_event(
            event_id="evt123",
            account_id="acc456",
            calendar_id="cal789",
            series_update_mode="future",
        )

        assert result["success"] is True
        assert result["seriesUpdateMode"] == "future"

    @pytest.mark.asyncio
    async def test_delete_event_api_error(self, mock_morgen_client):
        """Test event deletion with API error."""
        mock_morgen_client.delete_event.side_effect = MorgenAPIError(
            "Event not found", status_code=404
        )

        result = await delete_event(
            event_id="nonexistent",
            account_id="acc456",
            calendar_id="cal789",
        )

        assert "error" in result
        assert result["status_code"] == 404


class TestToolOutputFormat:
    """Tests for consistent tool output format."""

    @pytest.mark.asyncio
    async def test_success_response_has_success_key(self, mock_morgen_client):
        """Test that success responses include success key."""
        mock_morgen_client.update_calendar_metadata.return_value = None

        result = await update_calendar_metadata(
            calendar_id="cal123",
            account_id="acc456",
            busy=True,
        )

        assert "success" in result
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_error_response_has_error_key(self, mock_morgen_client):
        """Test that error responses include error key."""
        mock_morgen_client.list_calendars.side_effect = MorgenAPIError(
            "Test error", status_code=500
        )

        result = await list_calendars()

        assert "error" in result
        assert "status_code" in result

    @pytest.mark.asyncio
    async def test_list_response_has_count(self, mock_morgen_client):
        """Test that list responses include count."""
        mock_morgen_client.list_calendars.return_value = []

        result = await list_calendars()

        assert "count" in result
        assert result["count"] == 0
