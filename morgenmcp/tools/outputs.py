"""Typed output schemas for MCP tool return values.

These output models give each tool a shaped `outputSchema` instead of the
permissive ``{"type": "object", "additionalProperties": true}`` that a bare
``-> dict`` annotation produces. FastMCP 3.4.x validates each tool's return
against this schema at runtime.

**Why so many `NotRequired` fields:** item builders use ``filter_none_values``
(``tools/utils.py``) to drop keys whose values are None or ``[]``. This helper
is shallow: nested item builders must filter their own optional fields too.
A field marked *required* here that gets filtered out at runtime
would raise ``ToolError: Output validation error: '<field>' is a required
property`` on perfectly normal responses (an account with no display name, an
event with no description). So any field that ``filter_none_values`` — or
conditional construction — can drop is ``NotRequired``. Only keys that are
*always* present in the emitted dict are required.

Event listings and task models use Pydantic with `MISSING` for fields that can
be omitted. Pydantic leaves those fields out of serialization and describes
them as optional in the schema.

These are output-only view models. They intentionally do **not** reuse the
Pydantic wire models in ``models.py``: those are alias-based request/response
models whose shapes (snake_case fields, different nesting) differ from the
hand-built camelCase dicts the tools emit.
"""

from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict

from pydantic import MISSING, BaseModel, Field, WithJsonSchema


class FetchCoverage(TypedDict):
    fetch_limit: Annotated[int, Field(description="Limit sent to Morgen.")]
    limit_reached: Annotated[
        bool,
        Field(
            description="The upstream row count reached the limit before local filtering."
        ),
    ]


def fetch_coverage(limit: int, row_count: int) -> FetchCoverage:
    return {"fetch_limit": limit, "limit_reached": row_count >= limit}


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


class EventLocation(BaseModel):
    name: str | MISSING = MISSING


class EventParticipant(BaseModel):
    name: str | MISSING = MISSING
    email: str | MISSING = MISSING
    status: str | MISSING = MISSING
    isOrganizer: bool | MISSING = MISSING


class EventRecurrenceRule(BaseModel):
    frequency: str | MISSING = MISSING
    interval: int | MISSING = MISSING
    byDay: list[str] | MISSING = MISSING


class EventAlert(BaseModel):
    offset: str | MISSING = MISSING
    action: str | MISSING = MISSING


class EventItem(BaseModel):
    """One full event with virtual IDs and omittable fields."""

    id: str
    calendarId: str
    accountId: str
    isRecurring: bool
    title: str | MISSING = MISSING
    description: str | MISSING = MISSING
    start: str | MISSING = MISSING
    duration: str | MISSING = MISSING
    timeZone: str | MISSING = MISSING
    isAllDay: bool | MISSING = MISSING
    status: str | MISSING = MISSING
    privacy: str | MISSING = MISSING
    locations: list[EventLocation] | MISSING = MISSING
    participants: list[EventParticipant] | MISSING = MISSING
    recurrenceRules: list[EventRecurrenceRule] | MISSING = MISSING
    recurrenceId: str | MISSING = MISSING
    masterEventId: str | MISSING = MISSING
    alerts: list[EventAlert] | MISSING = MISSING
    useDefaultAlerts: bool | MISSING = MISSING
    googleColorId: str | MISSING = MISSING
    categoryId: str | MISSING = MISSING
    categoryName: str | MISSING = MISSING
    categoryColor: str | MISSING = MISSING
    taskId: str | MISSING = MISSING
    progress: str | MISSING = MISSING
    canBeCompleted: bool | MISSING = MISSING
    isAutoScheduled: bool | MISSING = MISSING
    virtualRoomUrl: str | MISSING = MISSING


class ListEventsResult(BaseModel):
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


class TaskListOutput(BaseModel):
    """One task list / space with task count."""

    id: str
    name: str
    color: str | None
    task_count: int = Field(
        description="Open tasks observed for this list in the upstream fetch."
    )
    account_id: str | None


class TaskListListOutput(BaseModel):
    task_lists: list[TaskListOutput]
    count: int = Field(description="Number of task lists returned.")
    coverage: FetchCoverage


class TaskRelationRef(BaseModel):
    """Relation flags inside ``TaskItem.relatedTo`` (JSCalendar ``Relation.relation``)."""

    relation: dict[str, bool] | MISSING = Field(
        default=MISSING,
        description="Relationship flags for the referenced task. For example, "
        '{"parent": true} identifies it as this task’s parent.',
    )


class TaskItem(BaseModel):
    """One task with virtual IDs and omittable fields."""

    id: str
    accountId: str | MISSING = MISSING
    integrationId: str | MISSING = MISSING
    taskListId: str | MISSING = MISSING
    title: str | MISSING = MISSING
    description: str | MISSING = MISSING
    due: str | MISSING = MISSING
    timeZone: str | MISSING = MISSING
    estimatedDuration: str | MISSING = MISSING
    priority: int | MISSING = MISSING
    progress: str | MISSING = MISSING
    # Preserve integer positions in JSON while advertising the existing number schema.
    position: Annotated[int | float, WithJsonSchema({"type": "number"})] | MISSING = (
        MISSING
    )
    relatedTo: dict[str, TaskRelationRef] | MISSING = Field(
        default=MISSING,
        description="Relationships keyed by the virtual IDs of the referenced tasks.",
    )
    tags: list[str] | MISSING = MISSING
    scheduled: bool | MISSING = MISSING
    created: str | MISSING = MISSING
    updated: str | MISSING = MISSING
    deleted: bool | MISSING = MISSING


class ListTasksResult(BaseModel):
    tasks: list[TaskItem]
    count: int = Field(description="Number of tasks returned after filtering.")
    coverage: FetchCoverage


class GetTaskResult(BaseModel):
    task: TaskItem


class CreatedTaskRef(BaseModel):
    id: str


class CreateTaskResult(BaseModel):
    success: bool
    message: str
    task: CreatedTaskRef


class MutateTaskResult(BaseModel):
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
    count: Annotated[int, Field(description="Number of tags returned.")]
    coverage: NotRequired[FetchCoverage]


class CreateTagResult(TypedDict):
    success: bool
    message: str
    tag: TagItem


class MutateTagResult(TypedDict):
    """Return of ``update_tag`` / ``delete_tag``."""

    success: bool
    message: str
    tagId: str
