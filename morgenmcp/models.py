"""Pydantic models for Morgen API responses.

Based on JSCalendar-inspired schema from Morgen documentation.
See: https://docs.morgen.so
"""

from typing import Literal
from pydantic import BaseModel, Field


class MorgenModel(BaseModel):
    """Base model with shared config for all Morgen API models."""

    model_config = {"populate_by_name": True}


class CalendarRights(MorgenModel):
    """Permissions for a calendar."""

    may_read_free_busy: bool = Field(alias="mayReadFreeBusy", default=False)
    may_read_items: bool = Field(alias="mayReadItems", default=False)
    may_write_all: bool = Field(alias="mayWriteAll", default=False)
    may_write_own: bool = Field(alias="mayWriteOwn", default=False)
    may_update_private: bool = Field(alias="mayUpdatePrivate", default=False)
    may_rsvp: bool = Field(alias="mayRSVP", default=False)
    may_admin: bool = Field(alias="mayAdmin", default=False)
    may_delete: bool = Field(alias="mayDelete", default=False)


class CalendarMetadata(MorgenModel):
    """Morgen-specific calendar metadata."""

    busy: bool | None = None
    override_color: str | None = Field(alias="overrideColor", default=None)
    override_name: str | None = Field(alias="overrideName", default=None)


class OffsetTrigger(MorgenModel):
    """Alert trigger with offset from event start."""

    type: Literal["OffsetTrigger"] = Field(alias="@type", default="OffsetTrigger")
    offset: str  # ISO 8601 duration, e.g., "-PT30M"
    relative_to: str = Field(alias="relativeTo", default="start")


class Alert(MorgenModel):
    """Calendar event alert."""

    type: Literal["Alert"] = Field(alias="@type", default="Alert")
    trigger: OffsetTrigger
    action: str = "display"


class Calendar(MorgenModel):
    """Morgen calendar model."""

    type: Literal["Calendar"] = Field(alias="@type", default="Calendar")
    id: str
    account_id: str = Field(alias="accountId")
    integration_id: str = Field(alias="integrationId")
    name: str | None = None
    color: str | None = None
    sort_order: int = Field(alias="sortOrder", default=0)
    my_rights: CalendarRights | None = Field(alias="myRights", default=None)
    default_alerts_with_time: dict[str, Alert] | None = Field(
        alias="defaultAlertsWithTime", default=None
    )
    default_alerts_without_time: dict[str, Alert] | None = Field(
        alias="defaultAlertsWithoutTime", default=None
    )
    metadata: CalendarMetadata | None = Field(alias="morgen.so:metadata", default=None)


class CalendarUpdateRequest(MorgenModel):
    """Request to update calendar metadata."""

    id: str
    account_id: str = Field(alias="accountId")
    metadata: CalendarMetadata = Field(alias="morgen.so:metadata")


class Location(MorgenModel):
    """Event location."""

    type: Literal["Location"] = Field(alias="@type", default="Location")
    name: str | None = None


class ParticipantRoles(MorgenModel):
    """Participant roles in an event."""

    attendee: bool = False
    owner: bool = False


class Participant(MorgenModel):
    """Event participant."""

    type: Literal["Participant"] = Field(alias="@type", default="Participant")
    name: str | None = None
    email: str | None = None
    roles: ParticipantRoles | None = None
    account_owner: bool = Field(alias="accountOwner", default=False)
    participation_status: str = Field(alias="participationStatus", default="needs-action")


class NDay(MorgenModel):
    """Day component in recurrence rule."""

    type: Literal["NDay"] = Field(alias="@type", default="NDay")
    day: str  # "mo", "tu", "we", "th", "fr", "sa", "su"


class RecurrenceRule(MorgenModel):
    """Recurrence rule for repeating events."""

    type: Literal["RecurrenceRule"] = Field(alias="@type", default="RecurrenceRule")
    frequency: str  # "daily", "weekly", "monthly", "yearly"
    interval: int = 1
    by_day: list[NDay] | None = Field(alias="byDay", default=None)


class VirtualRoom(MorgenModel):
    """Derived virtual room information."""

    url: str | None = None


class EventDerived(MorgenModel):
    """Morgen-derived event fields (read-only)."""

    virtual_room: VirtualRoom | None = Field(alias="virtualRoom", default=None)


class EventMetadata(MorgenModel):
    """Morgen-specific event metadata."""

    updated: str | None = None
    category_id: str | None = Field(alias="categoryId", default=None)
    category_name: str | None = Field(alias="categoryName", default=None)
    category_color: str | None = Field(alias="categoryColor", default=None)
    progress: str | None = None  # "needs-action", "completed"
    task_id: str | None = Field(alias="taskId", default=None)


class Event(MorgenModel):
    """Morgen calendar event model."""

    type: Literal["Event"] = Field(alias="@type", default="Event")
    id: str
    uid: str | None = None
    calendar_id: str = Field(alias="calendarId")
    account_id: str = Field(alias="accountId")
    integration_id: str = Field(alias="integrationId")
    base_event_id: str | None = Field(alias="baseEventId", default=None)
    master_event_id: str | None = Field(alias="masterEventId", default=None)
    master_base_event_id: str | None = Field(alias="masterBaseEventId", default=None)
    created: str | None = None
    updated: str | None = None
    recurrence_id: str | None = Field(alias="recurrenceId", default=None)
    recurrence_id_time_zone: str | None = Field(alias="recurrenceIdTimeZone", default=None)
    title: str | None = None
    description: str | None = None
    description_content_type: str = Field(
        alias="descriptionContentType", default="text/plain"
    )
    start: str  # LocalDateTime format: "2023-03-01T10:15:00"
    time_zone: str | None = Field(alias="timeZone", default=None)
    duration: str  # ISO 8601 duration: "PT1H", "PT30M"
    show_without_time: bool = Field(alias="showWithoutTime", default=False)
    privacy: str = "public"  # "public", "private", "secret"
    free_busy_status: str = Field(alias="freeBusyStatus", default="busy")  # "free", "busy"
    locations: dict[str, Location] | None = None
    participants: dict[str, Participant] | None = None
    alerts: dict[str, Alert] | None = None
    use_default_alerts: bool = Field(alias="useDefaultAlerts", default=False)
    recurrence_rules: list[RecurrenceRule] | None = Field(alias="recurrenceRules", default=None)
    google_color_id: str | None = Field(alias="google.com:colorId", default=None)
    google_hangout_link: str | None = Field(alias="google.com:hangoutLink", default=None)
    derived: EventDerived | None = Field(alias="morgen.so:derived", default=None)
    metadata: EventMetadata | None = Field(alias="morgen.so:metadata", default=None)
    request_virtual_room: str | None = Field(alias="morgen.so:requestVirtualRoom", default=None)


class EventCreateRequest(MorgenModel):
    """Request to create a new event."""

    account_id: str = Field(alias="accountId")
    calendar_id: str = Field(alias="calendarId")
    title: str
    start: str  # LocalDateTime format
    duration: str  # ISO 8601 duration
    time_zone: str | None = Field(alias="timeZone", default=None)
    show_without_time: bool = Field(alias="showWithoutTime", default=False)
    description: str | None = None
    description_content_type: str | None = Field(alias="descriptionContentType", default=None)
    locations: dict[str, Location] | None = None
    participants: dict[str, Participant] | None = None
    alerts: dict[str, Alert] | None = None
    use_default_alerts: bool | None = Field(alias="useDefaultAlerts", default=None)
    privacy: str | None = None
    free_busy_status: str | None = Field(alias="freeBusyStatus", default=None)
    recurrence_rules: list[RecurrenceRule] | None = Field(alias="recurrenceRules", default=None)
    google_color_id: str | None = Field(alias="google.com:colorId", default=None)
    request_virtual_room: str | None = Field(alias="morgen.so:requestVirtualRoom", default=None)


class EventUpdateRequest(MorgenModel):
    """Request to update an existing event."""

    id: str | None = None
    account_id: str = Field(alias="accountId")
    calendar_id: str = Field(alias="calendarId")
    master_event_id: str | None = Field(alias="masterEventId", default=None)
    recurrence_id: str | None = Field(alias="recurrenceId", default=None)
    recurrence_id_time_zone: str | None = Field(alias="recurrenceIdTimeZone", default=None)
    title: str | None = None
    start: str | None = None
    duration: str | None = None
    time_zone: str | None = Field(alias="timeZone", default=None)
    show_without_time: bool | None = Field(alias="showWithoutTime", default=None)
    description: str | None = None
    description_content_type: str | None = Field(alias="descriptionContentType", default=None)
    locations: dict[str, Location] | None = None
    participants: dict[str, Participant | None] | None = None
    alerts: dict[str, Alert | None] | None = None
    use_default_alerts: bool | None = Field(alias="useDefaultAlerts", default=None)
    privacy: str | None = None
    free_busy_status: str | None = Field(alias="freeBusyStatus", default=None)
    recurrence_rules: list[RecurrenceRule] | None = Field(alias="recurrenceRules", default=None)
    google_color_id: str | None = Field(alias="google.com:colorId", default=None)
    request_virtual_room: str | None = Field(alias="morgen.so:requestVirtualRoom", default=None)


class EventDeleteRequest(MorgenModel):
    """Request to delete an event."""

    id: str
    account_id: str = Field(alias="accountId")
    calendar_id: str = Field(alias="calendarId")


class CalendarsListResponse(BaseModel):
    """Response from calendars list endpoint."""

    calendars: list[Calendar]


class EventsListResponse(BaseModel):
    """Response from events list endpoint."""

    events: list[Event]


class CreatedEventInfo(MorgenModel):
    """Information about a newly created event."""

    id: str
    calendar_id: str = Field(alias="calendarId")
    account_id: str = Field(alias="accountId")


class EventCreateResponse(MorgenModel):
    """Response from event create endpoint."""

    event: CreatedEventInfo


class APIResponse[T](BaseModel):
    """Generic API response wrapper."""

    data: T


class RateLimitInfo(BaseModel):
    """Rate limit information from response headers."""

    limit: int
    remaining: int
    reset_seconds: int


class MorgenAPIError(Exception):
    """Exception raised for Morgen API errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        rate_limit_info: RateLimitInfo | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.rate_limit_info = rate_limit_info
