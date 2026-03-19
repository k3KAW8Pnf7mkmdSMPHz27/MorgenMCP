"""MCP tools for Morgen tag operations."""

from fastmcp.exceptions import ToolError

from morgenmcp.client import get_client
from morgenmcp.tools.utils import filter_none_values, handle_tool_errors
from morgenmcp.validators import validate_hex_color


@handle_tool_errors
async def list_tags(updated_after: str | None = None) -> dict:
    """List all tags.

    Args:
        updated_after: Only return tags updated after this ISO 8601 datetime.
            When provided, deleted tags are also returned with deleted=True.

    Returns:
        Dictionary with 'tags' key containing list of tag objects.
    """
    client = get_client()
    tags = await client.list_tags(updated_after=updated_after)

    return {
        "tags": [
            filter_none_values(
                {
                    "id": t.id,
                    "name": t.name,
                    "color": t.color,
                    "deleted": t.deleted if t.deleted else None,
                }
            )
            for t in tags
        ],
        "count": len(tags),
    }


@handle_tool_errors
async def get_tag(tag_id: str) -> dict:
    """Get a single tag by ID.

    Args:
        tag_id: The tag UUID.

    Returns:
        Dictionary with tag details.
    """
    client = get_client()
    tag = await client.get_tag(tag_id)
    return filter_none_values(
        {
            "id": tag.id,
            "name": tag.name,
            "color": tag.color,
        }
    )


@handle_tool_errors
async def create_tag(
    name: str,
    color: str | None = None,
) -> dict:
    """Create a new tag.

    Args:
        name: Tag name (min 1 character).
        color: Hex color code (exactly 7 chars, e.g., "#FF0000").

    Returns:
        Dictionary with created tag details.
    """
    if not name or len(name) < 1:
        raise ToolError("Tag name must be at least 1 character.")
    if color:
        validate_hex_color(color)

    client = get_client()
    tag = await client.create_tag(name=name, color=color)

    return {
        "success": True,
        "message": "Tag created successfully.",
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
    }


@handle_tool_errors
async def update_tag(
    tag_id: str,
    name: str | None = None,
    color: str | None = None,
) -> dict:
    """Update a tag. Name and color cannot be unset once defined.

    Args:
        tag_id: The tag UUID to update.
        name: New name (min 1 character if provided).
        color: New hex color (exactly 7 chars if provided).

    Returns:
        Dictionary indicating success.
    """
    if color:
        validate_hex_color(color)

    client = get_client()
    await client.update_tag(tag_id=tag_id, name=name, color=color)

    return {
        "success": True,
        "message": "Tag updated successfully.",
        "tagId": tag_id,
    }


@handle_tool_errors
async def delete_tag(tag_id: str) -> dict:
    """Delete a tag (soft delete).

    Args:
        tag_id: The tag UUID to delete.

    Returns:
        Dictionary indicating success.
    """
    client = get_client()
    await client.delete_tag(tag_id)

    return {
        "success": True,
        "message": "Tag deleted successfully.",
        "tagId": tag_id,
    }
