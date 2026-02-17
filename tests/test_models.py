"""Unit tests for Pydantic models."""

from morgenmcp.models import (
    Alert,
    Calendar,
    CalendarMetadata,
    CalendarRights,
    CalendarsListResponse,
    CalendarUpdateRequest,
    Event,
    EventCreateRequest,
    EventCreateResponse,
    EventDeleteRequest,
    EventsListResponse,
    EventUpdateRequest,
    Location,
    MorgenAPIError,
    NDay,
    OffsetTrigger,
    Participant,
    ParticipantRoles,
    RateLimitInfo,
    RecurrenceRule,
)


class TestCalendarModels:
    """Tests for calendar-related models."""

    def test_calendar_rights_from_api_response(self):
        """Test CalendarRights deserialization with API field names."""
        data = {
            "mayReadFreeBusy": True,
            "mayReadItems": True,
            "mayWriteAll": True,
            "mayWriteOwn": True,
            "mayUpdatePrivate": False,
            "mayRSVP": True,
            "mayAdmin": False,
            "mayDelete": True,
        }
        rights = CalendarRights.model_validate(data)

        assert rights.may_read_free_busy is True
        assert rights.may_read_items is True
        assert rights.may_write_all is True
        assert rights.may_delete is True
        assert rights.may_admin is False

    def test_calendar_metadata_serialization(self):
        """Test CalendarMetadata serialization with aliases."""
        metadata = CalendarMetadata(
            busy=True,
            override_color="#ff0000",
            override_name="My Calendar",
        )
        data = metadata.model_dump(by_alias=True)

        assert data["busy"] is True
        assert data["overrideColor"] == "#ff0000"
        assert data["overrideName"] == "My Calendar"

    def test_calendar_from_api_response(self):
        """Test Calendar model from full API response."""
        data = {
            "@type": "Calendar",
            "id": "cal123",
            "accountId": "acc456",
            "integrationId": "google",
            "name": "Work Calendar",
            "color": "#88baf8",
            "sortOrder": 1,
            "myRights": {
                "mayReadFreeBusy": True,
                "mayReadItems": True,
                "mayWriteAll": True,
                "mayWriteOwn": True,
                "mayUpdatePrivate": True,
                "mayRSVP": True,
                "mayAdmin": True,
                "mayDelete": True,
            },
            "morgen.so:metadata": {
                "busy": True,
                "overrideColor": "#ff0000",
            },
        }
        calendar = Calendar.model_validate(data)

        assert calendar.id == "cal123"
        assert calendar.account_id == "acc456"
        assert calendar.integration_id == "google"
        assert calendar.name == "Work Calendar"
        assert calendar.my_rights is not None
        assert calendar.my_rights.may_write_all is True
        assert calendar.metadata is not None
        assert calendar.metadata.busy is True

    def test_calendar_update_request_serialization(self):
        """Test CalendarUpdateRequest serialization for API."""
        request = CalendarUpdateRequest(
            id="cal123",
            account_id="acc456",
            metadata=CalendarMetadata(busy=False, override_name="Renamed"),
        )
        data = request.model_dump(by_alias=True, exclude_none=True)

        assert data["id"] == "cal123"
        assert data["accountId"] == "acc456"
        assert data["morgen.so:metadata"]["busy"] is False
        assert data["morgen.so:metadata"]["overrideName"] == "Renamed"

    def test_calendars_list_response(self):
        """Test CalendarsListResponse parsing."""
        data = {
            "calendars": [
                {
                    "@type": "Calendar",
                    "id": "cal1",
                    "accountId": "acc1",
                    "integrationId": "google",
                },
                {
                    "@type": "Calendar",
                    "id": "cal2",
                    "accountId": "acc1",
                    "integrationId": "o365",
                },
            ]
        }
        response = CalendarsListResponse.model_validate(data)

        assert len(response.calendars) == 2
        assert response.calendars[0].id == "cal1"
        assert response.calendars[1].integration_id == "o365"


class TestEventModels:
    """Tests for event-related models."""

    def test_location_model(self):
        """Test Location model."""
        location = Location(name="Conference Room A")
        data = location.model_dump(by_alias=True)

        assert data["@type"] == "Location"
        assert data["name"] == "Conference Room A"

    def test_participant_model(self):
        """Test Participant model."""
        participant = Participant(
            name="John Doe",
            email="john@example.com",
            roles=ParticipantRoles(attendee=True, owner=False),
            participation_status="accepted",
        )
        data = participant.model_dump(by_alias=True)

        assert data["name"] == "John Doe"
        assert data["email"] == "john@example.com"
        assert data["participationStatus"] == "accepted"

    def test_recurrence_rule_model(self):
        """Test RecurrenceRule model."""
        rule = RecurrenceRule(
            frequency="weekly",
            interval=2,
            by_day=[NDay(day="mo"), NDay(day="we"), NDay(day="fr")],
        )
        data = rule.model_dump(by_alias=True)

        assert data["frequency"] == "weekly"
        assert data["interval"] == 2
        assert len(data["byDay"]) == 3

    def test_alert_model(self):
        """Test Alert model with offset trigger."""
        alert = Alert(
            trigger=OffsetTrigger(offset="-PT30M"),
            action="display",
        )
        data = alert.model_dump(by_alias=True)

        assert data["@type"] == "Alert"
        assert data["trigger"]["offset"] == "-PT30M"
        assert data["action"] == "display"

    def test_event_from_api_response(self):
        """Test Event model from full API response."""
        data = {
            "@type": "Event",
            "id": "evt123",
            "calendarId": "cal456",
            "accountId": "acc789",
            "integrationId": "google",
            "title": "Team Meeting",
            "description": "Weekly sync",
            "start": "2023-03-01T10:00:00",
            "duration": "PT1H",
            "timeZone": "Europe/Berlin",
            "showWithoutTime": False,
            "freeBusyStatus": "busy",
            "privacy": "public",
            "locations": {"1": {"@type": "Location", "name": "Room 101"}},
            "participants": {
                "john@example.com": {
                    "@type": "Participant",
                    "name": "John",
                    "email": "john@example.com",
                    "roles": {"attendee": True, "owner": True},
                    "participationStatus": "accepted",
                }
            },
        }
        event = Event.model_validate(data)

        assert event.id == "evt123"
        assert event.title == "Team Meeting"
        assert event.start == "2023-03-01T10:00:00"
        assert event.duration == "PT1H"
        assert event.time_zone == "Europe/Berlin"
        assert event.show_without_time is False
        assert event.locations is not None
        assert "1" in event.locations
        assert event.participants is not None
        assert "john@example.com" in event.participants

    def test_event_create_request_serialization(self):
        """Test EventCreateRequest serialization."""
        request = EventCreateRequest(
            account_id="acc123",
            calendar_id="cal456",
            title="New Event",
            start="2023-03-15T14:00:00",
            duration="PT30M",
            time_zone="America/New_York",
            show_without_time=False,
            description="Test event",
        )
        data = request.model_dump(by_alias=True, exclude_none=True)

        assert data["accountId"] == "acc123"
        assert data["calendarId"] == "cal456"
        assert data["title"] == "New Event"
        assert data["start"] == "2023-03-15T14:00:00"
        assert data["timeZone"] == "America/New_York"
        assert data["showWithoutTime"] is False

    def test_event_update_request_partial(self):
        """Test EventUpdateRequest with partial fields."""
        request = EventUpdateRequest(
            id="evt123",
            account_id="acc456",
            calendar_id="cal789",
            title="Updated Title",
        )
        data = request.model_dump(by_alias=True, exclude_none=True)

        assert data["id"] == "evt123"
        assert data["accountId"] == "acc456"
        assert data["title"] == "Updated Title"
        assert "start" not in data
        assert "duration" not in data

    def test_event_delete_request(self):
        """Test EventDeleteRequest serialization."""
        request = EventDeleteRequest(
            id="evt123",
            account_id="acc456",
            calendar_id="cal789",
        )
        data = request.model_dump(by_alias=True)

        assert data["id"] == "evt123"
        assert data["accountId"] == "acc456"
        assert data["calendarId"] == "cal789"

    def test_event_create_response(self):
        """Test EventCreateResponse parsing."""
        data = {
            "event": {
                "id": "new_evt_123",
                "calendarId": "cal456",
                "accountId": "acc789",
            }
        }
        response = EventCreateResponse.model_validate(data)

        assert response.event.id == "new_evt_123"
        assert response.event.calendar_id == "cal456"

    def test_events_list_response(self):
        """Test EventsListResponse parsing."""
        data = {
            "events": [
                {
                    "@type": "Event",
                    "id": "evt1",
                    "calendarId": "cal1",
                    "accountId": "acc1",
                    "integrationId": "google",
                    "start": "2023-03-01T09:00:00",
                    "duration": "PT1H",
                },
                {
                    "@type": "Event",
                    "id": "evt2",
                    "calendarId": "cal1",
                    "accountId": "acc1",
                    "integrationId": "google",
                    "start": "2023-03-01T14:00:00",
                    "duration": "PT30M",
                },
            ]
        }
        response = EventsListResponse.model_validate(data)

        assert len(response.events) == 2
        assert response.events[0].id == "evt1"
        assert response.events[1].duration == "PT30M"


class TestErrorModels:
    """Tests for error and utility models."""

    def test_rate_limit_info(self):
        """Test RateLimitInfo model."""
        info = RateLimitInfo(limit=250, remaining=100, reset_seconds=459)

        assert info.limit == 250
        assert info.remaining == 100
        assert info.reset_seconds == 459

    def test_morgen_api_error(self):
        """Test MorgenAPIError exception."""
        error = MorgenAPIError(
            "Rate limit exceeded",
            status_code=429,
            rate_limit_info=RateLimitInfo(limit=250, remaining=0, reset_seconds=300),
        )

        assert str(error) == "Rate limit exceeded"
        assert error.status_code == 429
        assert error.rate_limit_info is not None
        assert error.rate_limit_info.remaining == 0

    def test_morgen_api_error_minimal(self):
        """Test MorgenAPIError with minimal fields."""
        error = MorgenAPIError("Something went wrong")

        assert str(error) == "Something went wrong"
        assert error.status_code is None
        assert error.rate_limit_info is None


class TestModelEdgeCases:
    """Tests for edge cases and optional fields."""

    def test_calendar_with_minimal_fields(self):
        """Test Calendar with only required fields."""
        data = {
            "id": "cal123",
            "accountId": "acc456",
            "integrationId": "caldav",
        }
        calendar = Calendar.model_validate(data)

        assert calendar.id == "cal123"
        assert calendar.name is None
        assert calendar.color is None
        assert calendar.my_rights is None
        assert calendar.metadata is None

    def test_event_with_recurrence(self):
        """Test Event with recurrence fields."""
        data = {
            "@type": "Event",
            "id": "evt123",
            "calendarId": "cal456",
            "accountId": "acc789",
            "integrationId": "google",
            "start": "2023-03-06T10:00:00",
            "duration": "PT1H",
            "recurrenceId": "2023-03-13T10:00:00",
            "recurrenceIdTimeZone": "Europe/Berlin",
            "masterEventId": "master_evt_123",
            "recurrenceRules": [
                {
                    "@type": "RecurrenceRule",
                    "frequency": "weekly",
                    "interval": 1,
                    "byDay": [{"@type": "NDay", "day": "mo"}],
                }
            ],
        }
        event = Event.model_validate(data)

        assert event.recurrence_id == "2023-03-13T10:00:00"
        assert event.master_event_id == "master_evt_123"
        assert event.recurrence_rules is not None
        assert len(event.recurrence_rules) == 1
        assert event.recurrence_rules[0].frequency == "weekly"

    def test_participant_with_null_values_in_update(self):
        """Test that participants can be set to null in updates."""
        request = EventUpdateRequest(
            id="evt123",
            account_id="acc456",
            calendar_id="cal789",
            participants={"remove@example.com": None},
        )
        data = request.model_dump(by_alias=True, exclude_none=True)

        assert "participants" in data
        assert data["participants"]["remove@example.com"] is None
