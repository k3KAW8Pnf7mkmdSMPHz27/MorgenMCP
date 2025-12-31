"""Input validators for Morgen API parameters.

These validators provide strict rejection with helpful error messages.
They do NOT auto-fix inputs to avoid silent data corruption (e.g., stripping
Z suffix from datetime could shift events by hours).
"""

import re
from zoneinfo import available_timezones


# Pre-compile regex patterns for performance
LOCAL_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
ISO_DURATION_PATTERN = re.compile(
    r"^P(?:\d+Y)?(?:\d+M)?(?:\d+W)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$"
)
HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Cache available timezones for performance
_VALID_TIMEZONES: set[str] | None = None


def _get_valid_timezones() -> set[str]:
    """Get cached set of valid IANA timezones."""
    global _VALID_TIMEZONES
    if _VALID_TIMEZONES is None:
        _VALID_TIMEZONES = available_timezones()
    return _VALID_TIMEZONES


class ValidationError(ValueError):
    """Raised when input validation fails."""

    pass


def validate_local_datetime(value: str, field_name: str = "datetime") -> str:
    """Validate LocalDateTime format (YYYY-MM-DDTHH:mm:ss, no Z suffix).

    The Morgen API requires LocalDateTime format without timezone suffix.
    The timezone is specified separately in the timeZone field.

    Args:
        value: The datetime string to validate.
        field_name: Name of the field for error messages.

    Returns:
        The validated datetime string.

    Raises:
        ValidationError: If the format is invalid.
    """
    if not value:
        raise ValidationError(f"'{field_name}' cannot be empty")

    # Check for common mistakes
    if value.endswith("Z"):
        raise ValidationError(
            f"Invalid {field_name} format: '{value}'. "
            f"Remove the 'Z' suffix - use LocalDateTime format (e.g., '2023-03-01T10:00:00'). "
            f"The timezone should be specified separately in the timeZone parameter."
        )

    if "+" in value or (value.count("-") > 2):
        # Check for timezone offset like +00:00 or -05:00
        if re.search(r"[+-]\d{2}:\d{2}$", value):
            raise ValidationError(
                f"Invalid {field_name} format: '{value}'. "
                f"Remove the timezone offset - use LocalDateTime format (e.g., '2023-03-01T10:00:00'). "
                f"The timezone should be specified separately in the timeZone parameter."
            )

    if not LOCAL_DATETIME_PATTERN.match(value):
        raise ValidationError(
            f"Invalid {field_name} format: '{value}'. "
            f"Expected LocalDateTime format: YYYY-MM-DDTHH:mm:ss (e.g., '2023-03-01T10:00:00')"
        )

    return value


def validate_duration(value: str) -> str:
    """Validate ISO 8601 duration format.

    Args:
        value: The duration string to validate.

    Returns:
        The validated duration string.

    Raises:
        ValidationError: If the format is invalid.
    """
    if not value:
        raise ValidationError("'duration' cannot be empty")

    if not ISO_DURATION_PATTERN.match(value):
        raise ValidationError(
            f"Invalid duration format: '{value}'. "
            f"Use ISO 8601 duration format. Examples: "
            f"'PT1H' (1 hour), 'PT30M' (30 minutes), 'PT1H30M' (1.5 hours), 'P1D' (1 day)"
        )

    # Ensure the duration has actual content (not just "P" or "PT")
    if value in ("P", "PT"):
        raise ValidationError(
            f"Invalid duration: '{value}'. Duration must specify a time value. "
            f"Examples: 'PT1H' (1 hour), 'PT30M' (30 minutes)"
        )

    return value


def validate_timezone(value: str | None) -> str | None:
    """Validate IANA timezone identifier.

    Args:
        value: The timezone string to validate, or None for floating events.

    Returns:
        The validated timezone string, or None.

    Raises:
        ValidationError: If the timezone is invalid.
    """
    if value is None:
        return None

    if not value:
        raise ValidationError("'timeZone' cannot be an empty string (use None for floating events)")

    valid_timezones = _get_valid_timezones()

    if value not in valid_timezones:
        # Provide helpful suggestions for common mistakes
        suggestions = []
        if value.upper() in ("EST", "PST", "CST", "MST", "EDT", "PDT", "CDT", "MDT"):
            suggestions = [
                "America/New_York (Eastern)",
                "America/Chicago (Central)",
                "America/Denver (Mountain)",
                "America/Los_Angeles (Pacific)",
            ]
        elif value.upper().startswith("GMT") or value.upper().startswith("UTC"):
            suggestions = ["UTC", "Etc/GMT", "Europe/London"]
        elif value.upper() in ("CET", "CEST"):
            suggestions = ["Europe/Berlin", "Europe/Paris", "Europe/Rome"]

        error_msg = f"Invalid timezone: '{value}'. Use IANA timezone format."
        if suggestions:
            error_msg += f" Did you mean: {', '.join(suggestions)}?"
        else:
            error_msg += " Examples: 'Europe/Berlin', 'America/New_York', 'Asia/Tokyo', 'UTC'"

        raise ValidationError(error_msg)

    return value


def validate_email(value: str) -> str:
    """Validate email address format.

    This is a basic validation - it doesn't verify the email exists.

    Args:
        value: The email address to validate.

    Returns:
        The validated email address.

    Raises:
        ValidationError: If the format is invalid.
    """
    if not value:
        raise ValidationError("Email address cannot be empty")

    if not EMAIL_PATTERN.match(value):
        raise ValidationError(
            f"Invalid email format: '{value}'. Expected format: 'user@domain.com'"
        )

    return value


def validate_hex_color(value: str) -> str:
    """Validate hex color format (#RRGGBB).

    Args:
        value: The color string to validate.

    Returns:
        The validated color string.

    Raises:
        ValidationError: If the format is invalid.
    """
    if not value:
        raise ValidationError("Color cannot be empty")

    if not HEX_COLOR_PATTERN.match(value):
        raise ValidationError(
            f"Invalid color format: '{value}'. "
            f"Use hex format: '#RRGGBB' (e.g., '#FF5733', '#7EF2FC')"
        )

    return value


def validate_date_range(start: str, end: str, max_days: int = 180) -> None:
    """Validate that a date range is valid and within limits.

    Args:
        start: Start datetime in LocalDateTime format.
        end: End datetime in LocalDateTime format.
        max_days: Maximum allowed range in days (default: 180 = ~6 months).

    Raises:
        ValidationError: If the range is invalid.
    """
    from datetime import datetime

    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError as e:
        raise ValidationError(f"Cannot parse date range: {e}")

    if end_dt <= start_dt:
        raise ValidationError(
            f"'end' ({end}) must be after 'start' ({start})"
        )

    days_diff = (end_dt - start_dt).days
    if days_diff > max_days:
        raise ValidationError(
            f"Date range too large: {days_diff} days. "
            f"Maximum allowed is {max_days} days (~6 months). "
            f"The Morgen API recommends retrieving no more than 2 months at a time."
        )
