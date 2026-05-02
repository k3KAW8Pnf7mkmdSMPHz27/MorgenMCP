"""MCP tools for Morgen tag operations."""

from fastmcp.exceptions import ToolError

from morgenmcp.client import get_client
from morgenmcp.models import (
    Tag,
    TagCreateRequest,
    TagDeleteRequest,
    TagUpdateRequest,
)
from morgenmcp.tools.id_registry import register_id, resolve_id
from morgenmcp.tools.utils import filter_none_values, handle_tool_errors
from morgenmcp.validators import validate_hex_color


def _format_tag(tag: Tag) -> dict:
    return filter_none_values(
        {
            "id": register_id(tag.id),
            "name": tag.name,
            "color": tag.color,
            "updated": tag.updated,
            "deleted": tag.deleted,
        }
    )


@handle_tool_errors
async def list_tags(
    updated_after: str | None = None,
    limit: int | None = None,
) -> dict:
    """List user tags.

    Args:
        updated_after: ISO 8601 datetime; when provided, also returns
            tags marked deleted (deleted=True). Useful for incremental sync.
        limit: Maximum number of tags to return.

    Returns:
        Dictionary with 'tags' key containing list of tag objects, plus 'count'.
    """
    if limit is not None and limit < 1:
        raise ToolError("limit must be a positive integer")

    client = get_client()
    tags = await client.list_tags(limit=limit, updated_after=updated_after)

    return {
        "tags": [_format_tag(t) for t in tags],
        "count": len(tags),
    }


@handle_tool_errors
async def create_tag(
    name: str,
    color: str | None = None,
) -> dict:
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
) -> dict:
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
    if name is None and color is None:
        raise ToolError("At least one of name or color must be provided.")
    if name is not None and not name.strip():
        raise ToolError("name cannot be empty when provided")
    if color is not None:
        validate_hex_color(color)

    real_id = resolve_id(tag_id)
    request = TagUpdateRequest(id=real_id, name=name, color=color)

    client = get_client()
    await client.update_tag(request)

    return {
        "success": True,
        "message": "Tag updated successfully.",
        "tagId": tag_id,
    }


@handle_tool_errors
async def delete_tag(tag_id: str) -> dict:
    """Soft-delete a tag.

    The tag will appear in subsequent sync responses (when using
    `updated_after`) with deleted=True.

    Args:
        tag_id: Virtual ID of the tag.

    Returns:
        Dictionary indicating success.
    """
    real_id = resolve_id(tag_id)
    request = TagDeleteRequest(id=real_id)

    client = get_client()
    await client.delete_tag(request)

    return {
        "success": True,
        "message": "Tag deleted.",
        "tagId": tag_id,
    }
