"""Utility functions for MCP tools."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from fastmcp.exceptions import ToolError

from morgenmcp.models import Location, MorgenAPIError, Participant, ParticipantRoles
from morgenmcp.validators import ValidationError


def filter_none_values(d: dict[str, Any]) -> dict[str, Any]:
    """Remove keys with None values or empty lists from a dict.

    Args:
        d: Dictionary to filter.

    Returns:
        New dictionary with None values and empty lists removed.
    """
    return {k: v for k, v in d.items() if v is not None and v != []}


def handle_tool_errors(func: Callable) -> Callable:
    """Decorator to handle common tool errors consistently.

    Catches ValidationError, MorgenAPIError, and unexpected exceptions,
    raising ToolError so messages are always visible to LLMs.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs) -> dict:
        try:
            return await func(*args, **kwargs)
        except ToolError:
            raise
        except ValidationError as e:
            raise ToolError(f"Validation error: {e}") from e
        except MorgenAPIError as e:
            raise ToolError(f"API error (HTTP {e.status_code}): {e}") from e
        except Exception as e:
            raise ToolError(f"Unexpected error: {e}") from e

    return wrapper


def build_locations_dict(
    location: str | None, allow_empty: bool = False
) -> dict[str, Location] | None:
    """Build locations dict from a location string.

    Args:
        location: The location name, or None/empty string.
        allow_empty: If True, empty string returns {} (for removal).
                    If False, empty string returns None.

    Returns:
        Dict with location, empty dict for removal, or None.
    """
    if location is None:
        return None
    if not location:
        return {} if allow_empty else None
    return {"1": Location(name=location)}


def build_participants_dict(
    emails: list[str] | None,
) -> dict[str, Participant] | None:
    """Build participants dict from a list of email addresses.

    Args:
        emails: List of participant email addresses, or None.

    Returns:
        Dict mapping emails to Participant objects, or None.
    """
    if not emails:
        return None
    return {
        email: Participant(
            name=email.split("@")[0],
            email=email,
            roles=ParticipantRoles(attendee=True),
            participation_status="needs-action",
        )
        for email in emails
    }
