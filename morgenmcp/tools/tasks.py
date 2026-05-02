"""MCP tools for Morgen task operations."""

import asyncio
from typing import Any, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from morgenmcp.client import get_client
from morgenmcp.models import (
    Task,
    TaskCloseRequest,
    TaskCreateRequest,
    TaskDeleteRequest,
    TaskMoveRequest,
    TaskRelation,
    TaskReopenRequest,
    TaskUpdateRequest,
)
from morgenmcp.tools.id_registry import register_id, resolve_id, resolve_ids
from morgenmcp.tools.utils import filter_none_values, handle_tool_errors
from morgenmcp.validators import (
    validate_duration,
    validate_local_datetime,
    validate_priority,
    validate_progress,
    validate_timezone,
)


def _format_task(task: Task) -> dict[str, Any]:
    """Format a task for tool output, virtualizing IDs."""
    related = task.related_to or {}
    related_out = {
        register_id(parent_id): {
            "relation": rel.relation,
        }
        for parent_id, rel in related.items()
    }

    return filter_none_values(
        {
            "id": register_id(task.id),
            "accountId": register_id(task.account_id) if task.account_id else None,
            "integrationId": task.integration_id,
            "taskListId": task.task_list_id,
            "title": task.title,
            "description": task.description,
            "due": task.due,
            "timeZone": task.time_zone,
            "estimatedDuration": task.estimated_duration,
            "priority": task.priority,
            "progress": task.progress,
            "position": task.position,
            "relatedTo": related_out or None,
            "tags": [register_id(t) for t in (task.tags or [])] or None,
            "scheduled": task.derived.scheduled if task.derived else None,
            "created": task.created,
            "updated": task.updated,
        }
    )


def _build_related_to(parent_task_id: str | None) -> dict[str, TaskRelation] | None:
    """Build a relatedTo dict for a single parent task."""
    if not parent_task_id:
        return None
    real_parent_id = resolve_id(parent_task_id)
    return {real_parent_id: TaskRelation(relation={"parent": True})}


@handle_tool_errors
async def list_tasks(
    limit: int | None = None,
    updated_after: str | None = None,
) -> dict:
    """List Morgen tasks.

    Args:
        limit: Max tasks to return (1-100, default 100). The /tasks/list
            endpoint costs 10 rate-limit points per call regardless of limit.
        updated_after: ISO 8601 datetime; when provided, returns tasks
            updated/created after this timestamp. Useful for incremental sync.

    Returns:
        Dictionary with 'tasks' key containing list of task objects with
        virtual IDs, plus 'count'.
    """
    if limit is not None and (limit < 1 or limit > 100):
        raise ToolError("limit must be between 1 and 100")

    client = get_client()
    tasks = await client.list_tasks(limit=limit, updated_after=updated_after)

    return {
        "tasks": [_format_task(t) for t in tasks],
        "count": len(tasks),
    }


@handle_tool_errors
async def get_task(task_id: str) -> dict:
    """Retrieve a single task by virtual ID.

    Args:
        task_id: The virtual ID of the task.

    Returns:
        Dictionary with the task fields.
    """
    real_id = resolve_id(task_id)
    client = get_client()
    task = await client.get_task(real_id)
    return {"task": _format_task(task)}


@handle_tool_errors
async def create_task(
    title: str,
    description: str | None = None,
    due: str | None = None,
    time_zone: str | None = None,
    estimated_duration: str | None = None,
    task_list_id: str | None = None,
    priority: int | None = None,
    progress: Literal["needs-action", "completed"] | None = None,
    parent_task_id: str | None = None,
    tag_ids: list[str] | None = None,
) -> dict:
    """Create a new Morgen task.

    Args:
        title: Task title (1+ characters).
        description: Optional task description (plain text).
        due: Optional due date in LocalDateTime format ('YYYY-MM-DDTHH:mm:ss').
            Provide a `time_zone` whenever `due` is set.
        time_zone: IANA timezone for the due date (e.g., 'Europe/Berlin').
        estimated_duration: ISO 8601 duration estimate (e.g., 'PT2H').
        task_list_id: Optional task list ID. Pass through unchanged.
        priority: 0 (undefined) to 9 (lowest); 1 is highest.
        progress: Initial status — 'needs-action' or 'completed'.
        parent_task_id: Virtual ID of the parent task; creates a subtask.
        tag_ids: Virtual IDs of tags to apply.

    Returns:
        Dictionary with the created task's virtual ID.
    """
    if not title or not title.strip():
        raise ToolError("title cannot be empty")

    if due is not None:
        validate_local_datetime(due, "due")
    if time_zone is not None:
        validate_timezone(time_zone)
    if estimated_duration is not None:
        validate_duration(estimated_duration)
    if priority is not None:
        validate_priority(priority)
    if progress is not None:
        validate_progress(progress)

    real_tags = resolve_ids(tag_ids) if tag_ids else None

    request = TaskCreateRequest(
        title=title,
        description=description,
        due=due,
        time_zone=time_zone,
        estimated_duration=estimated_duration,
        task_list_id=task_list_id,
        priority=priority,
        progress=progress,
        related_to=_build_related_to(parent_task_id),
        tags=real_tags,
    )

    client = get_client()
    new_id = await client.create_task(request)

    return {
        "success": True,
        "message": "Task created successfully.",
        "task": {"id": register_id(new_id)},
    }


@handle_tool_errors
async def update_task(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    due: str | None = None,
    time_zone: str | None = None,
    estimated_duration: str | None = None,
    task_list_id: str | None = None,
    priority: int | None = None,
    progress: Literal["needs-action", "in-process", "completed", "failed", "cancelled"]
    | None = None,
    tag_ids: list[str] | None = None,
) -> dict:
    """Update a task. Patch semantics — only provided fields change.

    Args:
        task_id: Virtual ID of the task to update.
        title: New title.
        description: New description.
        due: New due date (LocalDateTime format).
        time_zone: New IANA timezone.
        estimated_duration: New ISO 8601 duration.
        task_list_id: Move to a different task list.
        priority: 0-9 (1 highest, 9 lowest).
        progress: New status.
        tag_ids: Virtual IDs of tags. Replaces the existing tag list.

    Returns:
        Dictionary indicating success.
    """
    if due is not None:
        validate_local_datetime(due, "due")
    if time_zone is not None:
        validate_timezone(time_zone)
    if estimated_duration is not None:
        validate_duration(estimated_duration)
    if priority is not None:
        validate_priority(priority)
    if progress is not None:
        validate_progress(progress)

    real_id = resolve_id(task_id)
    real_tags = resolve_ids(tag_ids) if tag_ids else None

    request = TaskUpdateRequest(
        id=real_id,
        title=title,
        description=description,
        due=due,
        time_zone=time_zone,
        estimated_duration=estimated_duration,
        task_list_id=task_list_id,
        priority=priority,
        progress=progress,
        tags=real_tags,
    )

    client = get_client()
    await client.update_task(request)

    return {
        "success": True,
        "message": "Task updated successfully.",
        "taskId": task_id,
    }


@handle_tool_errors
async def move_task(
    task_id: str,
    previous_task_id: str | None = None,
    parent_task_id: str | None = None,
    move_to_first: bool = False,
    move_to_root: bool = False,
) -> dict:
    """Reorder a task or change its parent.

    Args:
        task_id: Virtual ID of the task to move.
        previous_task_id: Virtual ID of the task this should appear after.
            Pass None to leave position unchanged. Set move_to_first=True
            to move to the first position.
        parent_task_id: Virtual ID of the new parent task. None leaves the
            parent unchanged. Set move_to_root=True to move out of any
            subtask hierarchy.
        move_to_first: If True, sends previousId=null to put the task first.
        move_to_root: If True, sends parentId=null to detach from any parent.

    Returns:
        Dictionary indicating success.
    """
    real_id = resolve_id(task_id)
    payload: dict[str, Any] = {"id": real_id}

    if move_to_first and previous_task_id is not None:
        raise ToolError("move_to_first conflicts with previous_task_id")
    if move_to_root and parent_task_id is not None:
        raise ToolError("move_to_root conflicts with parent_task_id")

    if move_to_first:
        payload["previous_id"] = None
    elif previous_task_id is not None:
        payload["previous_id"] = resolve_id(previous_task_id)

    if move_to_root:
        payload["parent_id"] = None
    elif parent_task_id is not None:
        payload["parent_id"] = resolve_id(parent_task_id)

    if "previous_id" not in payload and "parent_id" not in payload:
        raise ToolError(
            "move_task needs at least one of previous_task_id, parent_task_id, "
            "move_to_first, or move_to_root."
        )

    request = TaskMoveRequest.model_validate(payload)
    client = get_client()
    await client.move_task(request)

    return {
        "success": True,
        "message": "Task moved successfully.",
        "taskId": task_id,
    }


@handle_tool_errors
async def complete_task(
    task_id: str,
    occurrence_start: str | None = None,
) -> dict:
    """Mark a task as completed.

    Args:
        task_id: Virtual ID of the task.
        occurrence_start: For recurring tasks, ISO 8601 datetime of the
            specific occurrence to complete.

    Returns:
        Dictionary indicating success.
    """
    if occurrence_start is not None:
        validate_local_datetime(occurrence_start, "occurrence_start")

    real_id = resolve_id(task_id)
    request = TaskCloseRequest(id=real_id, occurrence_start=occurrence_start)

    client = get_client()
    await client.close_task(request)

    return {
        "success": True,
        "message": "Task marked complete.",
        "taskId": task_id,
    }


@handle_tool_errors
async def reopen_task(
    task_id: str,
    occurrence_start: str | None = None,
) -> dict:
    """Reopen a completed task.

    Args:
        task_id: Virtual ID of the task.
        occurrence_start: For recurring tasks, ISO 8601 datetime of the
            specific occurrence to reopen.

    Returns:
        Dictionary indicating success.
    """
    if occurrence_start is not None:
        validate_local_datetime(occurrence_start, "occurrence_start")

    real_id = resolve_id(task_id)
    request = TaskReopenRequest(id=real_id, occurrence_start=occurrence_start)

    client = get_client()
    await client.reopen_task(request)

    return {
        "success": True,
        "message": "Task reopened.",
        "taskId": task_id,
    }


@handle_tool_errors
async def delete_task(task_id: str) -> dict:
    """Permanently delete a task.

    Args:
        task_id: Virtual ID of the task.

    Returns:
        Dictionary indicating success.
    """
    real_id = resolve_id(task_id)
    request = TaskDeleteRequest(id=real_id)

    client = get_client()
    await client.delete_task(request)

    return {
        "success": True,
        "message": "Task deleted.",
        "taskId": task_id,
    }


@handle_tool_errors
async def batch_delete_tasks(
    task_ids: list[str],
    ctx: Context | None = None,
) -> dict:
    """Delete multiple tasks in a single tool call.

    Args:
        task_ids: List of virtual task IDs to delete.

    Returns:
        Dictionary with 'deleted' (list of virtual IDs) and 'failed'
        (list of {id, error}).
    """
    if not task_ids:
        return {"deleted": [], "failed": [], "message": "No tasks to delete."}

    client = get_client()
    deleted: list[str] = []
    failed: list[dict[str, str]] = []

    to_delete: list[tuple[str, str]] = []  # (virtual_id, real_id)
    for virtual_id in task_ids:
        try:
            real_id = resolve_id(virtual_id)
            to_delete.append((virtual_id, real_id))
        except Exception as e:
            failed.append({"id": virtual_id, "error": str(e)})

    async def _delete(real_id: str) -> None:
        await client.delete_task(TaskDeleteRequest(id=real_id))

    results = await asyncio.gather(
        *(_delete(real_id) for _, real_id in to_delete),
        return_exceptions=True,
    )

    for i, result in enumerate(results):
        virtual_id = to_delete[i][0]
        if isinstance(result, Exception):
            if ctx:
                await ctx.warning(f"Failed to delete task {virtual_id}: {result}")
            failed.append({"id": virtual_id, "error": str(result)})
        else:
            deleted.append(virtual_id)

    return {
        "deleted": deleted,
        "failed": failed,
        "summary": f"Deleted {len(deleted)}, failed {len(failed)}",
    }
