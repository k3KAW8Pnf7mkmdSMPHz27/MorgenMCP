"""Utility functions for MCP tools."""

from functools import wraps
from typing import Callable

from morgenmcp.models import Location, MorgenAPIError, Participant, ParticipantRoles
from morgenmcp.validators import ValidationError


def handle_tool_errors(func: Callable) -> Callable:
    """Decorator to handle common tool errors consistently.

    Catches ValidationError, MorgenAPIError, and unexpected exceptions,
    returning appropriate error dicts.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs) -> dict:
        try:
            return await func(*args, **kwargs)
        except ValidationError as e:
            return {"error": str(e), "validation_error": True}
        except MorgenAPIError as e:
            return {"error": str(e), "status_code": e.status_code}
        except Exception as e:
            return {"error": f"Unexpected error: {e}"}

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
