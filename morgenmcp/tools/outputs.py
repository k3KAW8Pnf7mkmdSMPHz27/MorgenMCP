"""Typed output schemas for MCP tool return values.

These `TypedDict`s give each tool a shaped `outputSchema` instead of the
permissive ``{"type": "object", "additionalProperties": true}`` that a bare
``-> dict`` annotation produces. FastMCP 3.4.x validates each tool's return
against this schema at runtime.

**Why so many `NotRequired` fields:** every list/item payload is built through
``filter_none_values`` (``tools/utils.py``), which drops any key whose value is
None or ``[]``. A field marked *required* here that gets filtered out at runtime
would raise ``ToolError: Output validation error: '<field>' is a required
property`` on perfectly normal responses (an account with no display name, an
event with no description). So any field that ``filter_none_values`` — or
conditional construction — can drop is ``NotRequired``. Only keys that are
*always* present in the emitted dict are required.

These are output-only view models. They intentionally do **not** reuse the
Pydantic wire models in ``models.py``: those are alias-based request/response
models whose shapes (snake_case fields, different nesting) differ from the
hand-built camelCase dicts the tools emit.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


class AccountItem(TypedDict):
    """One connected calendar account (``list_accounts``)."""

    id: str
    integrationId: str
    email: NotRequired[str]
    displayName: NotRequired[str]


class ListAccountsResult(TypedDict):
    accounts: list[AccountItem]
    count: int


# ---------------------------------------------------------------------------
# Calendars
# ---------------------------------------------------------------------------


class CalendarPermissions(TypedDict):
    """Per-calendar rights; every sub-key is filtered when None."""

    canRead: NotRequired[bool]
    canWrite: NotRequired[bool]
    canDelete: NotRequired[bool]


class CalendarMetadata(TypedDict):
    """Morgen-specific calendar overrides; every sub-key is filtered when None."""

    busy: NotRequired[bool]
    overrideColor: NotRequired[str]
    overrideName: NotRequired[str]


class CalendarItem(TypedDict):
    """One calendar (``list_calendars``)."""

    id: str
    accountId: str
    integrationId: NotRequired[str]
    name: NotRequired[str]
    color: NotRequired[str]
    sortOrder: NotRequired[int]
    permissions: NotRequired[CalendarPermissions]
    metadata: NotRequired[CalendarMetadata]


class ListCalendarsResult(TypedDict):
    calendars: list[CalendarItem]
    count: int


class UpdatedCalendarMetadata(TypedDict):
    """Echo of an ``update_calendar_metadata`` change.

    Keys are always present (this dict is not run through
    ``filter_none_values``), but their values are nullable: a busy-only update
    leaves ``overrideColor``/``overrideName`` as None.
    """

    calendarId: str
    busy: bool | None
    overrideColor: str | None
    overrideName: str | None


class UpdateCalendarMetadataResult(TypedDict):
    success: bool
    message: str
    updated: UpdatedCalendarMetadata


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class EventLocation(TypedDict):
    name: NotRequired[str]


class EventParticipant(TypedDict):
    name: NotRequired[str]
    email: NotRequired[str]
    status: NotRequired[str]
    isOrganizer: NotRequired[bool]


class EventRecurrenceRule(TypedDict):
    frequency: NotRequired[str]
    interval: NotRequired[int]
    byDay: NotRequired[list[str]]


class EventAlert(TypedDict):
    offset: NotRequired[str]
    action: NotRequired[str]


class EventItem(TypedDict):
    """One event in full (non-compact) format (``_format_full_event``).

    Only ``id``/``calendarId``/``accountId``/``isRecurring`` are always emitted;
    everything else is dropped by ``filter_none_values`` when empty, so all are
    ``NotRequired``. (``locations``/``participants`` are always assigned but may
    be empty lists, which ``filter_none_values`` also drops.)
    """

    id: str
    calendarId: str
    accountId: str
    isRecurring: bool
    title: NotRequired[str]
    description: NotRequired[str]
    start: NotRequired[str]
    duration: NotRequired[str]
    timeZone: NotRequired[str]
    isAllDay: NotRequired[bool]
    status: NotRequired[str]
    privacy: NotRequired[str]
    locations: NotRequired[list[EventLocation]]
    participants: NotRequired[list[EventParticipant]]
    recurrenceRules: NotRequired[list[EventRecurrenceRule]]
    recurrenceId: NotRequired[str]
    masterEventId: NotRequired[str]
    alerts: NotRequired[list[EventAlert]]
    useDefaultAlerts: NotRequired[bool]
    googleColorId: NotRequired[str]
    categoryId: NotRequired[str]
    categoryName: NotRequired[str]
    categoryColor: NotRequired[str]
    taskId: NotRequired[str]
    virtualRoomUrl: NotRequired[str]


class ListEventsResult(TypedDict):
    """``list_events`` output. ``events`` is a list of ``EventItem`` in full
    mode, or a list of formatted strings when ``compact=True``."""

    events: list[EventItem] | list[str]
    count: int


class CreatedEventRef(TypedDict):
    id: str
    calendarId: str
    accountId: str


class CreateEventResult(TypedDict):
    success: bool
    message: str
    event: CreatedEventRef


class MutateEventResult(TypedDict):
    """Return of ``update_event`` / ``delete_event``."""

    success: bool
    message: str
    eventId: str
    seriesUpdateMode: str


# ---------------------------------------------------------------------------
# Batch operations (events + tasks)
# ---------------------------------------------------------------------------


class FailedItem(TypedDict):
    """A single per-item failure in a batch result."""

    id: str
    error: str


class BatchDeleteResult(TypedDict):
    """Return of ``batch_delete_events`` / ``batch_delete_tasks``.

    The empty-input early return emits ``message`` and omits ``summary``; the
    populated path emits ``summary`` and omits ``message`` — so exactly one of
    the two is present and both are ``NotRequired``.
    """

    deleted: list[str]
    failed: list[FailedItem]
    summary: NotRequired[str]
    message: NotRequired[str]


class BatchUpdateResult(TypedDict):
    """Return of ``batch_update_events`` (see ``BatchDeleteResult`` for the
    ``summary``/``message`` split)."""

    updated: list[str]
    failed: list[FailedItem]
    summary: NotRequired[str]
    message: NotRequired[str]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


class TaskRelationRef(TypedDict):
    relation: NotRequired[str]


class TaskItem(TypedDict):
    """One task (``_format_task``). Only ``id`` is always emitted; every other
    field is dropped by ``filter_none_values`` when empty."""

    id: str
    accountId: NotRequired[str]
    integrationId: NotRequired[str]
    taskListId: NotRequired[str]
    title: NotRequired[str]
    description: NotRequired[str]
    due: NotRequired[str]
    timeZone: NotRequired[str]
    estimatedDuration: NotRequired[str]
    priority: NotRequired[int]
    progress: NotRequired[str]
    position: NotRequired[int]
    relatedTo: NotRequired[dict[str, TaskRelationRef]]
    tags: NotRequired[list[str]]
    scheduled: NotRequired[str]
    created: NotRequired[str]
    updated: NotRequired[str]


class ListTasksResult(TypedDict):
    tasks: list[TaskItem]
    count: int


class GetTaskResult(TypedDict):
    task: TaskItem


class CreatedTaskRef(TypedDict):
    id: str


class CreateTaskResult(TypedDict):
    success: bool
    message: str
    task: CreatedTaskRef


class MutateTaskResult(TypedDict):
    """Return of ``update_task`` / ``move_task`` / ``complete_task`` /
    ``reopen_task`` / ``delete_task``."""

    success: bool
    message: str
    taskId: str


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


class TagItem(TypedDict):
    """One tag (``_format_tag``). Only ``id`` is always emitted."""

    id: str
    name: NotRequired[str]
    color: NotRequired[str]
    updated: NotRequired[str]
    deleted: NotRequired[bool]


class ListTagsResult(TypedDict):
    tags: list[TagItem]
    count: int


class CreateTagResult(TypedDict):
    success: bool
    message: str
    tag: TagItem


class MutateTagResult(TypedDict):
    """Return of ``update_tag`` / ``delete_tag``."""

    success: bool
    message: str
    tagId: str
