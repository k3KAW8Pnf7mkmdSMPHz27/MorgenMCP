"""MCP tools for Morgen task operations."""

from typing import Any, Literal

from fastmcp import Context
from fastmcp.exceptions import ToolError

from morgenmcp.client import get_client
from morgenmcp.models import (
    Task,
    TaskCreateRequest,
    TaskMoveRequest,
    TaskUpdateRequest,
)
from morgenmcp.tools.id_registry import register_id, resolve_id
from morgenmcp.tools.utils import filter_none_values, handle_tool_errors
from morgenmcp.validators import validate_duration, validate_local_datetime


def _format_compact_task(task: Task) -> str:
    """Format a task in compact one-liner format with virtual ID."""
    virtual_id = register_id(task.id)
    title = task.title or "(No title)"
    status = "✓" if task.progress == "completed" else "○"
    priority_str = f" P{task.priority}" if task.priority and task.priority > 0 else ""
    due_str = ""
    if task.due:
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(task.due)
            due_str = f" due:{dt.strftime('%b %d')}"
        except ValueError, TypeError:
            due_str = f" due:{task.due}"
    return f"{status}{priority_str} {title}{due_str} [{virtual_id}]"


def _format_full_task(task: Task) -> dict[str, Any]:
    """Format a task with all fields and virtual IDs."""
    result = filter_none_values(
        {
            "id": register_id(task.id),
            "title": task.title,
            "description": task.description,
            "progress": task.progress,
            "priority": task.priority,
            "due": task.due,
            "timeZone": task.time_zone,
            "estimatedDuration": task.estimated_duration,
            "taskListId": task.task_list_id,
            "tags": task.tags,
            "position": task.position,
            "created": task.created,
            "updated": task.updated,
        }
    )
    # Handle relatedTo — register parent task IDs
    if task.related_to:
        related = {}
        for parent_id, relation in task.related_to.items():
            related[register_id(parent_id)] = relation
        result["relatedTo"] = related
    return result


@handle_tool_errors
async def list_tasks(
    updated_after: str | None = None,
    compact: bool = False,
    ctx: Context | None = None,
) -> dict:
    """List all Morgen tasks.

    Note: This endpoint costs 10 rate limit points per request.

    Args:
        updated_after: Only return tasks updated after this ISO 8601 datetime.
        compact: If True, returns compact one-liner format to reduce tokens.
            Format: "○ P1 Task title due:Mar 15 [task_id]"

    Returns:
        Dictionary with 'tasks' key containing list of task objects (or strings if compact).
    """
    client = get_client()
    tasks = await client.list_tasks(updated_after=updated_after)

    if compact:
        return {
            "tasks": [_format_compact_task(t) for t in tasks],
            "count": len(tasks),
        }
    return {
        "tasks": [_format_full_task(t) for t in tasks],
        "count": len(tasks),
    }


@handle_tool_errors
async def get_task(task_id: str) -> dict:
    """Get a single task by ID.

    Args:
        task_id: The virtual ID of the task.

    Returns:
        Dictionary with full task details.
    """
    real_id = resolve_id(task_id)
    client = get_client()
    task = await client.get_task(real_id)
    return _format_full_task(task)


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
    tags: list[str] | None = None,
) -> dict:
    """Create a new task in Morgen.

    Args:
        title: Task title (required, min 1 character).
        description: Optional task description.
        due: Due date in LocalDateTime format (e.g., "2023-03-15T17:00:00").
        time_zone: IANA timezone for the due date (e.g., "America/New_York").
        estimated_duration: Estimated duration in ISO 8601 (e.g., "PT2H").
        task_list_id: Target task list ID (e.g., "default"). Uses default if omitted.
        priority: Priority 0-9 (0=undefined, 1=highest, 9=lowest).
        progress: Initial status: "needs-action" or "completed".
        parent_task_id: Virtual ID of parent task to create this as a subtask.
        tags: List of tag UUIDs to assign.

    Returns:
        Dictionary with created task ID.
    """
    if due:
        validate_local_datetime(due, "due")
    if estimated_duration:
        validate_duration(estimated_duration)
    if priority is not None and (priority < 0 or priority > 9):
        raise ToolError(
            "Priority must be between 0 and 9 (0=undefined, 1=highest, 9=lowest)"
        )

    # Build relatedTo for subtasks
    related_to = None
    if parent_task_id:
        real_parent_id = resolve_id(parent_task_id)
        related_to = {
            real_parent_id: {
                "@type": "Relation",
                "relation": {"parent": True},
            }
        }

    request = TaskCreateRequest(
        title=title,
        description=description,
        due=due,
        time_zone=time_zone,
        estimated_duration=estimated_duration,
        task_list_id=task_list_id,
        priority=priority,
        progress=progress,
        related_to=related_to,
        tags=tags,
    )

    client = get_client()
    result = await client.create_task(request)

    return {
        "success": True,
        "message": "Task created successfully.",
        "taskId": register_id(result.id),
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
    progress: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Update an existing task. Only provide fields you want to change.

    Args:
        task_id: Virtual ID of the task to update.
        title: Updated title.
        description: Updated description.
        due: Updated due date in LocalDateTime format.
        time_zone: Updated timezone.
        estimated_duration: Updated estimated duration.
        task_list_id: Move task to a different list.
        priority: Updated priority (0-9).
        progress: Updated status ("needs-action", "in-process", "completed", etc.).
        tags: Updated list of tag UUIDs.

    Returns:
        Dictionary indicating success.
    """
    real_task_id = resolve_id(task_id)

    if due:
        validate_local_datetime(due, "due")
    if estimated_duration:
        validate_duration(estimated_duration)
    if priority is not None and (priority < 0 or priority > 9):
        raise ToolError("Priority must be between 0 and 9")

    request = TaskUpdateRequest(
        id=real_task_id,
        title=title,
        description=description,
        due=due,
        time_zone=time_zone,
        estimated_duration=estimated_duration,
        task_list_id=task_list_id,
        priority=priority,
        progress=progress,
        tags=tags,
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
    previous_id: str | None = None,
    parent_id: str | None = None,
) -> dict:
    """Reorder a task or change its parent for subtask hierarchies.

    Args:
        task_id: Virtual ID of the task to move.
        previous_id: Virtual ID of the task this should appear after. None = move to first.
        parent_id: Virtual ID of parent task. None = move to root level.

    Returns:
        Dictionary indicating success.
    """
    real_task_id = resolve_id(task_id)
    real_previous_id = resolve_id(previous_id) if previous_id else None
    real_parent_id = resolve_id(parent_id) if parent_id else None

    request = TaskMoveRequest(
        id=real_task_id,
        previous_id=real_previous_id,
        parent_id=real_parent_id,
    )

    client = get_client()
    await client.move_task(request)

    return {
        "success": True,
        "message": "Task moved successfully.",
        "taskId": task_id,
    }


@handle_tool_errors
async def delete_task(task_id: str) -> dict:
    """Delete a task permanently.

    Args:
        task_id: Virtual ID of the task to delete.

    Returns:
        Dictionary indicating success.
    """
    real_task_id = resolve_id(task_id)
    client = get_client()
    await client.delete_task(real_task_id)

    return {
        "success": True,
        "message": "Task deleted successfully.",
        "taskId": task_id,
    }


@handle_tool_errors
async def close_task(
    task_id: str,
    occurrence_start: str | None = None,
) -> dict:
    """Mark a task as completed.

    Args:
        task_id: Virtual ID of the task to close.
        occurrence_start: For recurring tasks: ISO 8601 datetime of specific occurrence.

    Returns:
        Dictionary indicating success.
    """
    real_task_id = resolve_id(task_id)
    client = get_client()
    await client.close_task(real_task_id, occurrence_start=occurrence_start)

    return {
        "success": True,
        "message": "Task marked as completed.",
        "taskId": task_id,
    }


@handle_tool_errors
async def reopen_task(
    task_id: str,
    occurrence_start: str | None = None,
) -> dict:
    """Reopen a completed task.

    Args:
        task_id: Virtual ID of the task to reopen.
        occurrence_start: For recurring tasks: ISO 8601 datetime of specific occurrence.

    Returns:
        Dictionary indicating success.
    """
    real_task_id = resolve_id(task_id)
    client = get_client()
    await client.reopen_task(real_task_id, occurrence_start=occurrence_start)

    return {
        "success": True,
        "message": "Task reopened.",
        "taskId": task_id,
    }
