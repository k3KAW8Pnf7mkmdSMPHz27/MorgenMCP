"""Pydantic models for Morgen API responses.

Based on JSCalendar-inspired schema from Morgen documentation.
See: https://docs.morgen.so
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class MorgenModel(BaseModel):
    """Base model with shared config for all Morgen API models."""

    model_config = {"validate_by_name": True, "validate_by_alias": True}


class CalendarRights(MorgenModel):
    """Permissions for a calendar."""

    may_read_free_busy: Annotated[bool, Field(alias="mayReadFreeBusy")] = False
    may_read_items: Annotated[bool, Field(alias="mayReadItems")] = False
    may_write_all: Annotated[bool, Field(alias="mayWriteAll")] = False
    may_write_own: Annotated[bool, Field(alias="mayWriteOwn")] = False
    may_update_private: Annotated[bool, Field(alias="mayUpdatePrivate")] = False
    may_rsvp: Annotated[bool, Field(alias="mayRSVP")] = False
    may_admin: Annotated[bool, Field(alias="mayAdmin")] = False
    may_delete: Annotated[bool, Field(alias="mayDelete")] = False


class CalendarMetadata(MorgenModel):
    """Morgen-specific calendar metadata."""

    busy: bool | None = None
    override_color: Annotated[str | None, Field(alias="overrideColor")] = None
    override_name: Annotated[str | None, Field(alias="overrideName")] = None


class OffsetTrigger(MorgenModel):
    """Alert trigger with offset from event start."""

    type: Annotated[Literal["OffsetTrigger"], Field(alias="@type")] = "OffsetTrigger"
    offset: str  # ISO 8601 duration, e.g., "-PT30M"
    relative_to: Annotated[str, Field(alias="relativeTo")] = "start"


class Alert(MorgenModel):
    """Calendar event alert."""

    type: Annotated[Literal["Alert"], Field(alias="@type")] = "Alert"
    trigger: OffsetTrigger
    action: str = "display"


class Calendar(MorgenModel):
    """Morgen calendar model."""

    type: Annotated[Literal["Calendar"], Field(alias="@type")] = "Calendar"
    id: str
    account_id: Annotated[str, Field(alias="accountId")]
    integration_id: Annotated[str, Field(alias="integrationId")]
    name: str | None = None
    color: str | None = None
    sort_order: Annotated[int, Field(alias="sortOrder")] = 0
    my_rights: Annotated[CalendarRights | None, Field(alias="myRights")] = None
    default_alerts_with_time: Annotated[
        dict[str, Alert] | None, Field(alias="defaultAlertsWithTime")
    ] = None
    default_alerts_without_time: Annotated[
        dict[str, Alert] | None, Field(alias="defaultAlertsWithoutTime")
    ] = None
    metadata: Annotated[CalendarMetadata | None, Field(alias="morgen.so:metadata")] = (
        None
    )


class CalendarUpdateRequest(MorgenModel):
    """Request to update calendar metadata."""

    id: str
    account_id: Annotated[str, Field(alias="accountId")]
    metadata: Annotated[CalendarMetadata, Field(alias="morgen.so:metadata")]


class Location(MorgenModel):
    """Event location."""

    type: Annotated[Literal["Location"], Field(alias="@type")] = "Location"
    name: str | None = None


class ParticipantRoles(MorgenModel):
    """Participant roles in an event."""

    attendee: bool = False
    owner: bool = False


class Participant(MorgenModel):
    """Event participant."""

    type: Annotated[Literal["Participant"], Field(alias="@type")] = "Participant"
    name: str | None = None
    email: str | None = None
    roles: ParticipantRoles | None = None
    account_owner: Annotated[bool, Field(alias="accountOwner")] = False
    participation_status: Annotated[str, Field(alias="participationStatus")] = (
        "needs-action"
    )


class NDay(MorgenModel):
    """Day component in recurrence rule."""

    type: Annotated[Literal["NDay"], Field(alias="@type")] = "NDay"
    day: str  # "mo", "tu", "we", "th", "fr", "sa", "su"


class RecurrenceRule(MorgenModel):
    """Recurrence rule for repeating events."""

    type: Annotated[Literal["RecurrenceRule"], Field(alias="@type")] = "RecurrenceRule"
    frequency: str  # "daily", "weekly", "monthly", "yearly"
    interval: int = 1
    by_day: Annotated[list[NDay] | None, Field(alias="byDay")] = None


class VirtualRoom(MorgenModel):
    """Derived virtual room information."""

    url: str | None = None


class EventDerived(MorgenModel):
    """Morgen-derived event fields (read-only)."""

    virtual_room: Annotated[VirtualRoom | None, Field(alias="virtualRoom")] = None


class EventMetadata(MorgenModel):
    """Morgen-specific event metadata."""

    updated: str | None = None
    category_id: Annotated[str | None, Field(alias="categoryId")] = None
    category_name: Annotated[str | None, Field(alias="categoryName")] = None
    category_color: Annotated[str | None, Field(alias="categoryColor")] = None
    progress: str | None = None  # "needs-action", "completed"
    task_id: Annotated[str | None, Field(alias="taskId")] = None


class Event(MorgenModel):
    """Morgen calendar event model."""

    type: Annotated[Literal["Event"], Field(alias="@type")] = "Event"
    id: str
    uid: str | None = None
    calendar_id: Annotated[str, Field(alias="calendarId")]
    account_id: Annotated[str, Field(alias="accountId")]
    integration_id: Annotated[str, Field(alias="integrationId")]
    base_event_id: Annotated[str | None, Field(alias="baseEventId")] = None
    master_event_id: Annotated[str | None, Field(alias="masterEventId")] = None
    master_base_event_id: Annotated[str | None, Field(alias="masterBaseEventId")] = None
    created: str | None = None
    updated: str | None = None
    recurrence_id: Annotated[str | None, Field(alias="recurrenceId")] = None
    recurrence_id_time_zone: Annotated[
        str | None, Field(alias="recurrenceIdTimeZone")
    ] = None
    title: str | None = None
    description: str | None = None
    description_content_type: Annotated[str, Field(alias="descriptionContentType")] = (
        "text/plain"
    )
    start: str  # LocalDateTime format: "2023-03-01T10:15:00"
    time_zone: Annotated[str | None, Field(alias="timeZone")] = None
    duration: str  # ISO 8601 duration: "PT1H", "PT30M"
    show_without_time: Annotated[bool, Field(alias="showWithoutTime")] = False
    privacy: str = "public"  # "public", "private", "secret"
    free_busy_status: Annotated[str, Field(alias="freeBusyStatus")] = (
        "busy"  # "free", "busy"
    )
    locations: dict[str, Location] | None = None
    participants: dict[str, Participant] | None = None
    alerts: dict[str, Alert] | None = None
    use_default_alerts: Annotated[bool, Field(alias="useDefaultAlerts")] = False
    recurrence_rules: Annotated[
        list[RecurrenceRule] | None, Field(alias="recurrenceRules")
    ] = None
    google_color_id: Annotated[str | None, Field(alias="google.com:colorId")] = None
    google_hangout_link: Annotated[
        str | None, Field(alias="google.com:hangoutLink")
    ] = None
    derived: Annotated[EventDerived | None, Field(alias="morgen.so:derived")] = None
    metadata: Annotated[EventMetadata | None, Field(alias="morgen.so:metadata")] = None
    request_virtual_room: Annotated[
        str | None, Field(alias="morgen.so:requestVirtualRoom")
    ] = None


class EventCreateRequest(MorgenModel):
    """Request to create a new event."""

    account_id: Annotated[str, Field(alias="accountId")]
    calendar_id: Annotated[str, Field(alias="calendarId")]
    title: str
    start: str  # LocalDateTime format
    duration: str  # ISO 8601 duration
    time_zone: Annotated[str | None, Field(alias="timeZone")] = None
    show_without_time: Annotated[bool, Field(alias="showWithoutTime")] = False
    description: str | None = None
    description_content_type: Annotated[
        str | None, Field(alias="descriptionContentType")
    ] = None
    locations: dict[str, Location] | None = None
    participants: dict[str, Participant] | None = None
    alerts: dict[str, Alert] | None = None
    use_default_alerts: Annotated[bool | None, Field(alias="useDefaultAlerts")] = None
    privacy: str | None = None
    free_busy_status: Annotated[str | None, Field(alias="freeBusyStatus")] = None
    recurrence_rules: Annotated[
        list[RecurrenceRule] | None, Field(alias="recurrenceRules")
    ] = None
    google_color_id: Annotated[str | None, Field(alias="google.com:colorId")] = None
    request_virtual_room: Annotated[
        str | None, Field(alias="morgen.so:requestVirtualRoom")
    ] = None


class EventUpdateRequest(MorgenModel):
    """Request to update an existing event."""

    id: str | None = None
    account_id: Annotated[str, Field(alias="accountId")]
    calendar_id: Annotated[str, Field(alias="calendarId")]
    master_event_id: Annotated[str | None, Field(alias="masterEventId")] = None
    recurrence_id: Annotated[str | None, Field(alias="recurrenceId")] = None
    recurrence_id_time_zone: Annotated[
        str | None, Field(alias="recurrenceIdTimeZone")
    ] = None
    title: str | None = None
    start: str | None = None
    duration: str | None = None
    time_zone: Annotated[str | None, Field(alias="timeZone")] = None
    show_without_time: Annotated[bool | None, Field(alias="showWithoutTime")] = None
    description: str | None = None
    description_content_type: Annotated[
        str | None, Field(alias="descriptionContentType")
    ] = None
    locations: dict[str, Location] | None = None
    participants: dict[str, Participant | None] | None = None
    alerts: dict[str, Alert | None] | None = None
    use_default_alerts: Annotated[bool | None, Field(alias="useDefaultAlerts")] = None
    privacy: str | None = None
    free_busy_status: Annotated[str | None, Field(alias="freeBusyStatus")] = None
    recurrence_rules: Annotated[
        list[RecurrenceRule] | None, Field(alias="recurrenceRules")
    ] = None
    google_color_id: Annotated[str | None, Field(alias="google.com:colorId")] = None
    request_virtual_room: Annotated[
        str | None, Field(alias="morgen.so:requestVirtualRoom")
    ] = None


class EventDeleteRequest(MorgenModel):
    """Request to delete an event."""

    id: str
    account_id: Annotated[str, Field(alias="accountId")]
    calendar_id: Annotated[str, Field(alias="calendarId")]


class Account(MorgenModel):
    """Connected calendar account."""

    id: str
    provider_id: Annotated[str, Field(alias="providerId")]
    integration_id: Annotated[str, Field(alias="integrationId")]
    provider_user_id: Annotated[str, Field(alias="providerUserId")]
    provider_user_display_name: Annotated[str, Field(alias="providerUserDisplayName")]


class AccountsListResponse(BaseModel):
    """Response from accounts list endpoint."""

    accounts: list[Account]


class CalendarsListResponse(BaseModel):
    """Response from calendars list endpoint."""

    calendars: list[Calendar]


class EventsListResponse(BaseModel):
    """Response from events list endpoint."""

    events: list[Event]


class CreatedEventInfo(MorgenModel):
    """Information about a newly created event."""

    id: str
    calendar_id: Annotated[str, Field(alias="calendarId")]
    account_id: Annotated[str, Field(alias="accountId")]


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
