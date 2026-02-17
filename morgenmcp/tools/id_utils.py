"""Utilities for extracting IDs from Morgen's composite ID format.

Morgen IDs are base64-encoded JSON arrays:
- Calendar ID: [accountId, calendarEmail]
- Event ID: [calendarEmail, eventUid, accountId]

This allows deriving account_id and calendar_id from event_id without caching.
"""

import base64
import json


def _add_base64_padding(encoded: str) -> str:
    """Add padding to base64 string if needed."""
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    return encoded


def extract_account_from_calendar(calendar_id: str) -> str:
    """Extract account ID from a calendar ID.

    Calendar ID structure: base64([accountId, calendarEmail])

    Args:
        calendar_id: The real Morgen calendar ID.

    Returns:
        The account ID.
    """
    padded = _add_base64_padding(calendar_id)
    decoded = json.loads(base64.b64decode(padded))
    return decoded[0]


def extract_ids_from_event(event_id: str) -> tuple[str, str]:
    """Extract account ID and calendar ID from an event ID.

    Event ID structure: base64([calendarEmail, eventUid, accountId])

    Args:
        event_id: The real Morgen event ID.

    Returns:
        Tuple of (account_id, calendar_id)
    """
    padded = _add_base64_padding(event_id)
    decoded = json.loads(base64.b64decode(padded))
    # decoded = [calendarEmail, eventUid, accountId]
    account_id = decoded[2]
    calendar_email = decoded[0]
    # Reconstruct calendar ID: base64([accountId, calendarEmail])
    calendar_id = (
        base64.b64encode(
            json.dumps([account_id, calendar_email], separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )
    return account_id, calendar_id
