"""Utility functions for MCP tools."""

import base64
import json
from collections.abc import Callable
from functools import wraps
from typing import Any

from fastmcp.exceptions import ToolError

from morgenmcp.models import (
    Alert,
    Location,
    MorgenAPIError,
    NDay,
    OffsetTrigger,
    Participant,
    ParticipantRoles,
    RecurrenceRule,
)
from morgenmcp.validators import (
    ValidationError,
    validate_alert_offset,
    validate_recurrence_rule,
)


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


def _alert_id(offset: str, action: str = "display") -> str:
    """Compute the canonical alert ID: base64(JSON.stringify({a, to}, sorted keys))."""
    payload = json.dumps(
        {"a": action, "to": offset}, sort_keys=True, separators=(",", ":")
    )
    return base64.b64encode(payload.encode()).decode()


def build_alerts_dict(
    offsets: list[str] | None,
) -> dict[str, Alert | None] | None:
    """Build an alerts dict from a list of negative ISO 8601 offsets.

    Each entry becomes an Alert keyed by base64(JSON({a:'display',to:offset})),
    matching Morgen's deterministic alert-ID encoding.

    The return type uses `Alert | None` to match `EventUpdateRequest.alerts`,
    which permits None values for the patch-style "remove this alert" pattern.
    This builder never produces None values — only the broader signature.

    Args:
        offsets: List of negative duration strings (e.g., ['-PT15M', '-PT1H']).

    Returns:
        Dict mapping alert IDs to Alert objects, or None if offsets is None/empty.
    """
    if not offsets:
        return None
    alerts: dict[str, Alert | None] = {}
    for offset in offsets:
        validate_alert_offset(offset)
        alerts[_alert_id(offset)] = Alert(
            trigger=OffsetTrigger(offset=offset, relative_to="start"),
            action="display",
        )
    return alerts


def build_recurrence_rules(
    rules: list[dict[str, Any]] | None,
) -> list[RecurrenceRule] | None:
    """Convert simplified recurrence rule dicts into RecurrenceRule objects.

    Accepts dicts with keys: `frequency` (required), `interval` (default 1),
    `by_day` / `byDay` (optional list of two-letter weekday codes).

    Args:
        rules: List of rule dicts, or None.

    Returns:
        List of RecurrenceRule objects, or None.
    """
    if rules is None:
        return None
    if not rules:
        return []

    out: list[RecurrenceRule] = []
    for rule in rules:
        validate_recurrence_rule(rule)
        by_day_input = rule.get("by_day") or rule.get("byDay")
        by_day_objs: list[NDay] | None = None
        if by_day_input:
            by_day_objs = [
                NDay(day=d) if isinstance(d, str) else NDay(day=d["day"])
                for d in by_day_input
            ]
        out.append(
            RecurrenceRule(
                frequency=rule["frequency"],
                interval=rule.get("interval", 1),
                by_day=by_day_objs,
            )
        )
    return out
