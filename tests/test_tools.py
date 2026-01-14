"""Unit tests for MCP tools."""

import base64
import json
from unittest.mock import AsyncMock, patch

import pytest

from morgenmcp.models import (
    Account,
    Calendar,
    CalendarMetadata,
    CalendarRights,
    CreatedEventInfo,
    Event,
    EventCreateResponse,
    EventDerived,
    Location,
    MorgenAPIError,
    Participant,
    ParticipantRoles,
    VirtualRoom,
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
from morgenmcp.tools.id_registry import clear_registry, register_id


def assert_api_error(result: dict, status_code: int) -> None:
    """Assert that result contains an API error with the expected status code."""
    assert "error" in result
    assert result["status_code"] == status_code


def assert_validation_error(result: dict) -> None:
    """Assert that result contains a validation error."""
    assert "error" in result
    assert result.get("validation_error") is True


def make_calendar_id(account_id: str, calendar_email: str) -> str:
    """Create a Morgen-style calendar ID: base64([accountId, calendarEmail])."""
    return base64.b64encode(
        json.dumps([account_id, calendar_email], separators=(",", ":")).encode()
    ).decode().rstrip("=")


def make_event_id(calendar_email: str, event_uid: str, account_id: str) -> str:
    """Create a Morgen-style event ID: base64([calendarEmail, eventUid, accountId])."""
    return base64.b64encode(
        json.dumps([calendar_email, event_uid, account_id], separators=(",", ":")).encode()
    ).decode().rstrip("=")


@pytest.fixture(autouse=True)
def clear_id_registry():
    """Clear the ID registry before and after each test."""
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def mock_morgen_client():
    """Create a mock Morgen client."""
    with patch("morgenmcp.tools.accounts.get_client") as acc_mock, \
         patch("morgenmcp.tools.calendars.get_client") as cal_mock, \
         patch("morgenmcp.tools.events.get_client") as evt_mock:
        client = AsyncMock()
        acc_mock.return_value = client
        cal_mock.return_value = client
        evt_mock.return_value = client
        yield client


@pytest.fixture
def sample_account_id():
    """Real account ID (MongoDB ObjectId style)."""
    return "6954a6179c9d703795f281ce"


@pytest.fixture
def sample_calendar_email():
    """Sample calendar email."""
    return "test@example.com"


@pytest.fixture
def sample_calendar_id(sample_account_id, sample_calendar_email):
    """Morgen-style calendar ID."""
    return make_calendar_id(sample_account_id, sample_calendar_email)


@pytest.fixture
def sample_event_uid():
    """Sample event UID."""
    return "abc123eventuid"


@pytest.fixture
def sample_event_id(sample_calendar_email, sample_event_uid, sample_account_id):
    """Morgen-style event ID."""
    return make_event_id(sample_calendar_email, sample_event_uid, sample_account_id)


@pytest.fixture
def sample_calendar(sample_calendar_id, sample_account_id):
    """Create a sample calendar for testing."""
    return Calendar(
        id=sample_calendar_id,
        account_id=sample_account_id,
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
def sample_event(sample_event_id, sample_calendar_id, sample_account_id):
    """Create a sample event for testing."""
    return Event(
        id=sample_event_id,
        calendar_id=sample_calendar_id,
        account_id=sample_account_id,
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


@pytest.fixture
def sample_account(sample_account_id):
    """Create a sample account for testing."""
    return Account(
        id=sample_account_id,
        provider_id="provider-uuid-456",
        integration_id="google",
        provider_user_id="user@gmail.com",
        provider_user_display_name="Test User",
    )


class TestListAccounts:
    """Tests for list_accounts tool."""

    @pytest.mark.asyncio
    async def test_list_accounts_success(self, mock_morgen_client, sample_account):
        """Test successful account listing."""
        mock_morgen_client.list_accounts.return_value = [sample_account]

        result = await list_accounts()

        assert "accounts" in result
        assert result["count"] == 1
        # IDs are now virtualized (7-char Base64url)
        assert len(result["accounts"][0]["id"]) == 7
        assert result["accounts"][0]["integrationId"] == "google"
        assert result["accounts"][0]["email"] == "user@gmail.com"
        assert result["accounts"][0]["displayName"] == "Test User"

    @pytest.mark.asyncio
    async def test_list_accounts_empty(self, mock_morgen_client):
        """Test account listing with no accounts."""
        mock_morgen_client.list_accounts.return_value = []

        result = await list_accounts()

        assert result["accounts"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_accounts_api_error(self, mock_morgen_client):
        """Test account listing with API error."""
        mock_morgen_client.list_accounts.side_effect = MorgenAPIError(
            "Authentication failed", status_code=401
        )

        result = await list_accounts()

        assert_api_error(result, 401)

    @pytest.mark.asyncio
    async def test_list_accounts_multiple(self, mock_morgen_client):
        """Test listing multiple accounts."""
        accounts = [
            Account(
                id="acc1",
                provider_id="p1",
                integration_id="google",
                provider_user_id="user1@gmail.com",
                provider_user_display_name="User One",
            ),
            Account(
                id="acc2",
                provider_id="p2",
                integration_id="o365",
                provider_user_id="user2@outlook.com",
                provider_user_display_name="User Two",
            ),
        ]
        mock_morgen_client.list_accounts.return_value = accounts

        result = await list_accounts()

        assert result["count"] == 2
        assert result["accounts"][0]["integrationId"] == "google"
        assert result["accounts"][1]["integrationId"] == "o365"


class TestListCalendars:
    """Tests for list_calendars tool."""

    @pytest.mark.asyncio
    async def test_list_calendars_success(self, mock_morgen_client, sample_calendar):
        """Test successful calendar listing."""
        mock_morgen_client.list_calendars.return_value = [sample_calendar]

        result = await list_calendars()

        assert "calendars" in result
        assert result["count"] == 1
        # IDs are now virtualized (7-char Base64url)
        assert len(result["calendars"][0]["id"]) == 7
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

        assert_api_error(result, 429)

    @pytest.mark.asyncio
    async def test_list_calendars_with_no_metadata(self, mock_morgen_client, sample_calendar_id, sample_account_id):
        """Test calendar listing with calendar that has no metadata."""
        calendar = Calendar(
            id=sample_calendar_id,
            account_id=sample_account_id,
            integration_id="caldav",
        )
        mock_morgen_client.list_calendars.return_value = [calendar]

        result = await list_calendars()

        # Null fields are omitted from response
        assert "metadata" not in result["calendars"][0]
        assert "permissions" not in result["calendars"][0]


class TestUpdateCalendarMetadata:
    """Tests for update_calendar_metadata tool."""

    @pytest.mark.asyncio
    async def test_update_calendar_metadata_success(self, mock_morgen_client, sample_calendar_id):
        """Test successful calendar metadata update."""
        mock_morgen_client.update_calendar_metadata.return_value = None

        # Register calendar ID first (simulating list_calendars was called)
        virtual_cal = register_id(sample_calendar_id)

        result = await update_calendar_metadata(
            calendar_id=virtual_cal,
            busy=False,
            override_color="#00ff00",
        )

        assert result["success"] is True
        assert result["updated"]["calendarId"] == virtual_cal
        assert result["updated"]["busy"] is False

    @pytest.mark.asyncio
    async def test_update_calendar_metadata_no_fields(self, mock_morgen_client, sample_calendar_id):
        """Test update with no fields provided."""
        virtual_cal = register_id(sample_calendar_id)

        result = await update_calendar_metadata(
            calendar_id=virtual_cal,
        )

        assert "error" in result
        assert "At least one" in result["error"]

    @pytest.mark.asyncio
    async def test_update_calendar_metadata_api_error(self, mock_morgen_client, sample_calendar_id):
        """Test update with API error."""
        mock_morgen_client.update_calendar_metadata.side_effect = MorgenAPIError(
            "Calendar not found", status_code=404
        )

        virtual_cal = register_id(sample_calendar_id)

        result = await update_calendar_metadata(
            calendar_id=virtual_cal,
            busy=True,
        )

        assert_api_error(result, 404)


class TestListEvents:
    """Tests for list_events tool."""

    @pytest.mark.asyncio
    async def test_list_events_success(self, mock_morgen_client, sample_event, sample_calendar_id):
        """Test successful event listing with explicit calendars."""
        mock_morgen_client.list_events.return_value = [sample_event]

        # Register calendar ID first (simulating list_calendars was called)
        virtual_cal = register_id(sample_calendar_id)

        result = await list_events(
            start="2023-03-01T00:00:00",
            end="2023-03-02T00:00:00",
            calendar_ids=[virtual_cal],
        )

        assert "events" in result
        assert result["count"] == 1
        # IDs are now virtualized (7-char Base64url)
        assert len(result["events"][0]["id"]) == 7
        assert result["events"][0]["title"] == "Team Meeting"
        assert result["events"][0]["virtualRoomUrl"] == "https://meet.google.com/abc-defg-hij"
        assert len(result["events"][0]["participants"]) == 2

    @pytest.mark.asyncio
    async def test_list_events_empty(self, mock_morgen_client, sample_calendar_id):
        """Test event listing with no events."""
        mock_morgen_client.list_events.return_value = []

        virtual_cal = register_id(sample_calendar_id)

        result = await list_events(
            start="2023-03-01T00:00:00",
            end="2023-03-02T00:00:00",
            calendar_ids=[virtual_cal],
        )

        assert result["events"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_events_api_error(self, mock_morgen_client, sample_calendar_id):
        """Test event listing with API error."""
        mock_morgen_client.list_events.side_effect = MorgenAPIError(
            "Invalid date range", status_code=400
        )

        virtual_cal = register_id(sample_calendar_id)

        result = await list_events(
            start="2023-03-01T00:00:00",
            end="2023-03-02T00:00:00",
            calendar_ids=[virtual_cal],
        )

        assert_api_error(result, 400)

    @pytest.mark.asyncio
    async def test_list_events_validation_error(self, mock_morgen_client, sample_calendar_id):
        """Test event listing with validation error (Z suffix)."""
        virtual_cal = register_id(sample_calendar_id)

        result = await list_events(
            start="2023-03-01T00:00:00Z",
            end="2023-03-02T00:00:00",
            calendar_ids=[virtual_cal],
        )

        assert_validation_error(result)
        assert "Z" in result["error"]

    @pytest.mark.asyncio
    async def test_list_events_all_calendars(self, mock_morgen_client, sample_event, sample_calendar):
        """Test event listing without calendar_ids queries all calendars."""
        mock_morgen_client.list_calendars.return_value = [sample_calendar]
        mock_morgen_client.list_events.return_value = [sample_event]

        result = await list_events(
            start="2023-03-01T00:00:00",
            end="2023-03-02T00:00:00",
        )

        assert result["count"] == 1
        # Verify list_calendars was called
        mock_morgen_client.list_calendars.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_events_compact_mode(self, mock_morgen_client, sample_event, sample_calendar_id):
        """Test event listing with compact mode."""
        mock_morgen_client.list_events.return_value = [sample_event]

        virtual_cal = register_id(sample_calendar_id)

        result = await list_events(
            start="2023-03-01T00:00:00",
            end="2023-03-02T00:00:00",
            calendar_ids=[virtual_cal],
            compact=True,
        )

        assert result["count"] == 1
        # Compact format should be a string
        assert isinstance(result["events"][0], str)
        assert "Team Meeting" in result["events"][0]
        # Event ID is now a 7-char Base64url in brackets
        assert "[" in result["events"][0] and "]" in result["events"][0]

    @pytest.mark.asyncio
    async def test_list_events_compact_all_day(self, mock_morgen_client, sample_calendar_id, sample_account_id):
        """Test compact mode with all-day event."""
        all_day_event_id = make_event_id("test@example.com", "allday_uid", sample_account_id)
        all_day_event = Event(
            id=all_day_event_id,
            calendar_id=sample_calendar_id,
            account_id=sample_account_id,
            integration_id="google",
            title="Holiday",
            start="2023-03-15T00:00:00",
            duration="P1D",
            show_without_time=True,
        )
        mock_morgen_client.list_events.return_value = [all_day_event]

        virtual_cal = register_id(sample_calendar_id)

        result = await list_events(
            start="2023-03-01T00:00:00",
            end="2023-03-31T00:00:00",
            calendar_ids=[virtual_cal],
            compact=True,
        )

        assert "(all-day)" in result["events"][0]
        assert "Holiday" in result["events"][0]


class TestCreateEvent:
    """Tests for create_event tool."""

    @pytest.mark.asyncio
    async def test_create_event_success(self, mock_morgen_client, sample_calendar_id, sample_account_id):
        """Test successful event creation."""
        new_event_id = make_event_id("test@example.com", "new_evt_123", sample_account_id)
        mock_morgen_client.create_event.return_value = EventCreateResponse(
            event=CreatedEventInfo(
                id=new_event_id,
                calendar_id=sample_calendar_id,
                account_id=sample_account_id,
            )
        )

        # Register calendar ID first (simulating list_calendars was called)
        virtual_cal = register_id(sample_calendar_id)

        result = await create_event(
            calendar_id=virtual_cal,
            title="New Meeting",
            start="2023-03-15T14:00:00",
            duration="PT1H",
            time_zone="Europe/Berlin",
        )

        assert result["success"] is True
        # Event ID is now virtualized (7-char Base64url)
        assert len(result["event"]["id"]) == 7

    @pytest.mark.asyncio
    async def test_create_event_with_location(self, mock_morgen_client, sample_calendar_id, sample_account_id):
        """Test event creation with location."""
        new_event_id = make_event_id("test@example.com", "new_evt_123", sample_account_id)
        mock_morgen_client.create_event.return_value = EventCreateResponse(
            event=CreatedEventInfo(
                id=new_event_id,
                calendar_id=sample_calendar_id,
                account_id=sample_account_id,
            )
        )

        virtual_cal = register_id(sample_calendar_id)

        result = await create_event(
            calendar_id=virtual_cal,
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
    async def test_create_event_with_participants(self, mock_morgen_client, sample_calendar_id, sample_account_id):
        """Test event creation with participants."""
        new_event_id = make_event_id("test@example.com", "new_evt_123", sample_account_id)
        mock_morgen_client.create_event.return_value = EventCreateResponse(
            event=CreatedEventInfo(
                id=new_event_id,
                calendar_id=sample_calendar_id,
                account_id=sample_account_id,
            )
        )

        virtual_cal = register_id(sample_calendar_id)

        result = await create_event(
            calendar_id=virtual_cal,
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
    async def test_create_event_api_error(self, mock_morgen_client, sample_calendar_id):
        """Test event creation with API error."""
        mock_morgen_client.create_event.side_effect = MorgenAPIError(
            "Calendar not found", status_code=404
        )

        virtual_cal = register_id(sample_calendar_id)

        result = await create_event(
            calendar_id=virtual_cal,
            title="Bad Event",
            start="2023-03-15T14:00:00",
            duration="PT1H",
            time_zone="Europe/Berlin",
        )

        assert_api_error(result, 404)

    @pytest.mark.asyncio
    async def test_create_event_validation_error(self, mock_morgen_client, sample_calendar_id):
        """Test event creation with validation error (invalid duration)."""
        virtual_cal = register_id(sample_calendar_id)

        result = await create_event(
            calendar_id=virtual_cal,
            title="Bad Event",
            start="2023-03-15T14:00:00",
            duration="invalid",
            time_zone="Europe/Berlin",
        )

        assert_validation_error(result)
        assert "duration" in result["error"].lower()


class TestUpdateEvent:
    """Tests for update_event tool."""

    @pytest.mark.asyncio
    async def test_update_event_success(self, mock_morgen_client, sample_event_id):
        """Test successful event update."""
        mock_morgen_client.update_event.return_value = None

        # Register event ID first
        virtual_evt = register_id(sample_event_id)

        result = await update_event(
            event_id=virtual_evt,
            title="Updated Title",
        )

        assert result["success"] is True
        assert result["eventId"] == virtual_evt

    @pytest.mark.asyncio
    async def test_update_event_timing_fields_incomplete(self, mock_morgen_client, sample_event_id):
        """Test update with incomplete timing fields."""
        virtual_evt = register_id(sample_event_id)

        result = await update_event(
            event_id=virtual_evt,
            start="2023-03-15T14:00:00",
            # Missing duration, time_zone, is_all_day
        )

        assert "error" in result
        assert "all four must be provided" in result["error"]

    @pytest.mark.asyncio
    async def test_update_event_timing_fields_complete(self, mock_morgen_client, sample_event_id):
        """Test update with complete timing fields."""
        mock_morgen_client.update_event.return_value = None

        virtual_evt = register_id(sample_event_id)

        result = await update_event(
            event_id=virtual_evt,
            start="2023-03-15T14:00:00",
            duration="PT2H",
            time_zone="America/New_York",
            is_all_day=False,
        )

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_event_series_mode(self, mock_morgen_client, sample_event_id):
        """Test update with series update mode."""
        mock_morgen_client.update_event.return_value = None

        virtual_evt = register_id(sample_event_id)

        result = await update_event(
            event_id=virtual_evt,
            title="Updated Recurring",
            series_update_mode="all",
        )

        assert result["success"] is True
        assert result["seriesUpdateMode"] == "all"
        mock_morgen_client.update_event.assert_called_once()
        call_kwargs = mock_morgen_client.update_event.call_args[1]
        assert call_kwargs["series_update_mode"] == "all"

    @pytest.mark.asyncio
    async def test_update_event_api_error(self, mock_morgen_client, sample_event_id):
        """Test event update with API error."""
        mock_morgen_client.update_event.side_effect = MorgenAPIError(
            "Event not found", status_code=404
        )

        virtual_evt = register_id(sample_event_id)

        result = await update_event(
            event_id=virtual_evt,
            title="Updated",
        )

        assert_api_error(result, 404)


class TestDeleteEvent:
    """Tests for delete_event tool."""

    @pytest.mark.asyncio
    async def test_delete_event_success(self, mock_morgen_client, sample_event_id):
        """Test successful event deletion."""
        mock_morgen_client.delete_event.return_value = None

        virtual_evt = register_id(sample_event_id)

        result = await delete_event(event_id=virtual_evt)

        assert result["success"] is True
        assert result["eventId"] == virtual_evt

    @pytest.mark.asyncio
    async def test_delete_event_series_mode(self, mock_morgen_client, sample_event_id):
        """Test deletion with series update mode."""
        mock_morgen_client.delete_event.return_value = None

        virtual_evt = register_id(sample_event_id)

        result = await delete_event(
            event_id=virtual_evt,
            series_update_mode="future",
        )

        assert result["success"] is True
        assert result["seriesUpdateMode"] == "future"

    @pytest.mark.asyncio
    async def test_delete_event_api_error(self, mock_morgen_client, sample_event_id):
        """Test event deletion with API error."""
        mock_morgen_client.delete_event.side_effect = MorgenAPIError(
            "Event not found", status_code=404
        )

        virtual_evt = register_id(sample_event_id)

        result = await delete_event(event_id=virtual_evt)

        assert_api_error(result, 404)


class TestToolOutputFormat:
    """Tests for consistent tool output format."""

    @pytest.mark.asyncio
    async def test_success_response_has_success_key(self, mock_morgen_client, sample_calendar_id):
        """Test that success responses include success key."""
        mock_morgen_client.update_calendar_metadata.return_value = None

        virtual_cal = register_id(sample_calendar_id)

        result = await update_calendar_metadata(
            calendar_id=virtual_cal,
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


class TestBatchDeleteEvents:
    """Tests for batch_delete_events tool."""

    @pytest.mark.asyncio
    async def test_batch_delete_success(self, mock_morgen_client, sample_account_id):
        """Test successful batch deletion."""
        # Create two event IDs with proper Morgen structure
        evt_id1 = make_event_id("test@example.com", "uid1", sample_account_id)
        evt_id2 = make_event_id("test@example.com", "uid2", sample_account_id)
        virtual_evt1 = register_id(evt_id1)
        virtual_evt2 = register_id(evt_id2)
        mock_morgen_client.delete_event.return_value = None

        result = await batch_delete_events(event_ids=[virtual_evt1, virtual_evt2])

        assert result["deleted"] == [virtual_evt1, virtual_evt2]
        assert result["failed"] == []
        assert "Deleted 2" in result["summary"]

    @pytest.mark.asyncio
    async def test_batch_delete_unregistered_id(self, mock_morgen_client, sample_account_id):
        """Test batch deletion with unregistered event ID."""
        evt_id1 = make_event_id("test@example.com", "uid1", sample_account_id)
        virtual_evt1 = register_id(evt_id1)
        mock_morgen_client.delete_event.return_value = None

        result = await batch_delete_events(event_ids=[virtual_evt1, "unregistered"])

        assert result["deleted"] == [virtual_evt1]
        assert len(result["failed"]) == 1
        assert result["failed"][0]["id"] == "unregistered"
        assert "not found" in result["failed"][0]["error"]

    @pytest.mark.asyncio
    async def test_batch_delete_partial_failure(self, mock_morgen_client, sample_account_id):
        """Test batch deletion with partial API failure."""
        evt_id1 = make_event_id("test@example.com", "uid1", sample_account_id)
        evt_id2 = make_event_id("test@example.com", "uid2", sample_account_id)
        virtual_evt1 = register_id(evt_id1)
        virtual_evt2 = register_id(evt_id2)

        # First delete succeeds, second fails
        mock_morgen_client.delete_event.side_effect = [
            None,
            MorgenAPIError("Event not found", status_code=404),
        ]

        result = await batch_delete_events(event_ids=[virtual_evt1, virtual_evt2])

        assert virtual_evt1 in result["deleted"]
        assert any(f["id"] == virtual_evt2 for f in result["failed"])

    @pytest.mark.asyncio
    async def test_batch_delete_empty_list(self, mock_morgen_client):
        """Test batch deletion with empty list."""
        result = await batch_delete_events(event_ids=[])

        assert result["deleted"] == []
        assert result["failed"] == []
        assert "No events" in result["message"]


class TestBatchUpdateEvents:
    """Tests for batch_update_events tool."""

    @pytest.mark.asyncio
    async def test_batch_update_success(self, mock_morgen_client, sample_account_id):
        """Test successful batch update."""
        evt_id1 = make_event_id("test@example.com", "uid1", sample_account_id)
        evt_id2 = make_event_id("test@example.com", "uid2", sample_account_id)
        virtual_evt1 = register_id(evt_id1)
        virtual_evt2 = register_id(evt_id2)
        mock_morgen_client.update_event.return_value = None

        result = await batch_update_events(updates=[
            {"event_id": virtual_evt1, "title": "New Title 1"},
            {"event_id": virtual_evt2, "title": "New Title 2"},
        ])

        assert result["updated"] == [virtual_evt1, virtual_evt2]
        assert result["failed"] == []
        assert "Updated 2" in result["summary"]

    @pytest.mark.asyncio
    async def test_batch_update_unregistered_id(self, mock_morgen_client, sample_account_id):
        """Test batch update with unregistered event ID."""
        evt_id1 = make_event_id("test@example.com", "uid1", sample_account_id)
        virtual_evt1 = register_id(evt_id1)
        mock_morgen_client.update_event.return_value = None

        result = await batch_update_events(updates=[
            {"event_id": virtual_evt1, "title": "New Title"},
            {"event_id": "unregistered", "title": "Will Fail"},
        ])

        assert result["updated"] == [virtual_evt1]
        assert len(result["failed"]) == 1
        assert result["failed"][0]["id"] == "unregistered"

    @pytest.mark.asyncio
    async def test_batch_update_missing_event_id(self, mock_morgen_client):
        """Test batch update with missing event_id."""
        result = await batch_update_events(updates=[
            {"title": "No Event ID"},
        ])

        assert result["updated"] == []
        assert len(result["failed"]) == 1
        assert "Missing event_id" in result["failed"][0]["error"]

    @pytest.mark.asyncio
    async def test_batch_update_timing_validation(self, mock_morgen_client, sample_account_id):
        """Test batch update validates timing fields constraint."""
        evt_id1 = make_event_id("test@example.com", "uid1", sample_account_id)
        virtual_evt1 = register_id(evt_id1)

        result = await batch_update_events(updates=[
            {"event_id": virtual_evt1, "start": "2023-03-15T10:00:00"},  # Missing duration, time_zone, is_all_day
        ])

        assert result["updated"] == []
        assert len(result["failed"]) == 1
        assert "all four" in result["failed"][0]["error"]

    @pytest.mark.asyncio
    async def test_batch_update_empty_list(self, mock_morgen_client):
        """Test batch update with empty list."""
        result = await batch_update_events(updates=[])

        assert result["updated"] == []
        assert result["failed"] == []
        assert "No updates" in result["message"]

    @pytest.mark.asyncio
    async def test_batch_update_partial_failure(self, mock_morgen_client, sample_account_id):
        """Test batch update with partial API failure."""
        evt_id1 = make_event_id("test@example.com", "uid1", sample_account_id)
        evt_id2 = make_event_id("test@example.com", "uid2", sample_account_id)
        virtual_evt1 = register_id(evt_id1)
        virtual_evt2 = register_id(evt_id2)

        mock_morgen_client.update_event.side_effect = [
            None,
            MorgenAPIError("Event not found", status_code=404),
        ]

        result = await batch_update_events(updates=[
            {"event_id": virtual_evt1, "title": "Updated"},
            {"event_id": virtual_evt2, "title": "Will Fail"},
        ])

        assert virtual_evt1 in result["updated"]
        assert any(f["id"] == virtual_evt2 for f in result["failed"])
