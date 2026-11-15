"""MCP tools for Morgen tag operations."""

from __future__ import annotations

from typing import cast

from fastmcp.exceptions import ToolError

from morgenmcp.client import get_client
from morgenmcp.models import (
    MorgenAPIError,
    Tag,
    TagCreateRequest,
    TagDeleteRequest,
    TagUpdateRequest,
)
from morgenmcp.tools.id_registry import IDNotFoundError, register_id, resolve_id
from morgenmcp.tools.outputs import (
    CreateTagResult,
    ListTagsResult,
    MutateTagResult,
    TagItem,
    fetch_coverage,
)
from morgenmcp.tools.utils import (
    filter_none_values,
    handle_tool_errors,
    is_not_found,
)
from morgenmcp.validators import validate_hex_color


def _tag_not_found(tag_id: str) -> ToolError:
    return ToolError(f"Tag with ID '{tag_id}' not found")


def _resolve_tag_id(tag_id: str) -> str:
    """Validate and resolve a virtual tag ID to its real Morgen ID."""
    if not tag_id or not tag_id.strip():
        raise ToolError("tag_id cannot be empty")
    try:
        return resolve_id(tag_id)
    except IDNotFoundError as e:
        raise _tag_not_found(tag_id) from e


def _format_tag(tag: Tag) -> TagItem:
    return cast(
        "TagItem",
        filter_none_values(
            {
                "id": register_id(tag.id),
                "name": tag.name,
                "color": tag.color,
                "updated": tag.updated,
                "deleted": tag.deleted,
            }
        ),
    )


@handle_tool_errors
async def list_tags(
    updated_after: str | None = None,
    limit: int | None = None,
) -> ListTagsResult:
    """List user tags.

    Args:
        updated_after: ISO 8601 datetime; when provided, also returns
            tags marked deleted (deleted=True). Useful for incremental sync.
        limit: Maximum number of tags to return. Defaults to the server's
            configured MORGENMCP_TAGS_LIMIT; when unset, all tags are returned.

    Returns:
        Tags, their returned count, and fetch coverage when a limit is set.
    """
    if limit is not None and limit < 1:
        raise ToolError("limit must be a positive integer")

    client = get_client()
    tags, fetch_limit = await client.list_tags(limit=limit, updated_after=updated_after)

    result: ListTagsResult = {
        "tags": [_format_tag(t) for t in tags],
        "count": len(tags),
    }
    if fetch_limit is not None:
        result["coverage"] = fetch_coverage(fetch_limit, len(tags))
    return result


@handle_tool_errors
async def get_tag(tag_id: str) -> TagItem:
    """Retrieve a single tag by virtual ID.

    Args:
        tag_id: Virtual ID of the tag.

    Returns:
        Dictionary with tag details (id, name, color, updated, deleted).
    """
    real_id = _resolve_tag_id(tag_id)

    client = get_client()
    try:
        tag = await client.get_tag(real_id)
    except MorgenAPIError as e:
        # tags.mdx documents 404 as "Tag does not exist".
        if is_not_found(e):
            raise _tag_not_found(tag_id) from e
        raise

    return _format_tag(tag)


@handle_tool_errors
async def create_tag(
    name: str,
    color: str | None = None,
) -> CreateTagResult:
    """Create a new tag.

    Args:
        name: Tag name (1+ characters).
        color: Hex color (#RRGGBB) — exactly 7 chars including the leading '#'.

    Returns:
        Dictionary with the created tag's virtual ID, name, and color.
    """
    if not name or not name.strip():
        raise ToolError("name cannot be empty")
    if color is not None:
        validate_hex_color(color)

    request = TagCreateRequest(name=name, color=color)
    client = get_client()
    tag = await client.create_tag(request)

    return {
        "success": True,
        "message": "Tag created successfully.",
        "tag": _format_tag(tag),
    }


@handle_tool_errors
async def update_tag(
    tag_id: str,
    name: str | None = None,
    color: str | None = None,
) -> MutateTagResult:
    """Update a tag's name or color.

    Note: Morgen does not allow unsetting name or color once defined —
    only changing them to new values.

    Args:
        tag_id: Virtual ID of the tag.
        name: New name (1+ characters if provided).
        color: New hex color (#RRGGBB).

    Returns:
        Dictionary indicating success.
    """
    real_id = _resolve_tag_id(tag_id)
    if name is None and color is None:
        raise ToolError("At least one of name or color must be provided.")
    if name is not None and not name.strip():
        raise ToolError("name cannot be empty when provided")
    if color is not None:
        validate_hex_color(color)

    request = TagUpdateRequest(id=real_id, name=name, color=color)

    client = get_client()
    try:
        await client.update_tag(request)
    except MorgenAPIError as e:
        if is_not_found(e):
            raise _tag_not_found(tag_id) from e
        raise

    return {
        "success": True,
        "message": "Tag updated successfully.",
        "tagId": tag_id,
    }


@handle_tool_errors
async def delete_tag(tag_id: str) -> MutateTagResult:
    """Soft-delete a tag.

    The tag will appear in subsequent sync responses (when using
    `updated_after`) with deleted=True.

    Args:
        tag_id: Virtual ID of the tag.

    Returns:
        Dictionary indicating success.
    """
    real_id = _resolve_tag_id(tag_id)
    request = TagDeleteRequest(id=real_id)

    client = get_client()
    try:
        await client.delete_tag(request)
    except MorgenAPIError as e:
        # Unlike events, tags.mdx gives no idempotent-delete guidance: a 404
        # means the tag does not exist, which is reported as an error.
        if is_not_found(e):
            raise _tag_not_found(tag_id) from e
        raise

    return {
        "success": True,
        "message": "Tag deleted.",
        "tagId": tag_id,
    }
