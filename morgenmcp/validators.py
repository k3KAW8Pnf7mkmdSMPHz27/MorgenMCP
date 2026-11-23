"""Input validators for Morgen API parameters.

These validators provide strict rejection with helpful error messages.
They do NOT auto-fix inputs to avoid silent data corruption (e.g., stripping
Z suffix from datetime could shift events by hours).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, available_timezones

# Pre-compile regex patterns for performance
SUFFIXLESS_DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
EVENT_WINDOW_BOUND_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?$"
)
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

    # Check for timezone offset like +00:00 or -05:00
    if ("+" in value or value.count("-") > 2) and re.search(r"[+-]\d{2}:\d{2}$", value):
        raise ValidationError(
            f"Invalid {field_name} format: '{value}'. "
            "Remove the timezone offset - use LocalDateTime format "
            "(e.g., '2023-03-01T10:00:00'). "
            "The timezone should be specified separately in the timeZone parameter."
        )

    if not SUFFIXLESS_DATETIME_PATTERN.match(value):
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
        raise ValidationError(
            "'timeZone' cannot be an empty string (use None for floating events)"
        )

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
            error_msg += (
                " Examples: 'Europe/Berlin', 'America/New_York', 'Asia/Tokyo', 'UTC'"
            )

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


_VALID_TASK_PROGRESS = {
    "needs-action",
    "in-process",
    "completed",
    "failed",
    "cancelled",
}

_VALID_RECURRENCE_FREQUENCIES = {"daily", "weekly", "monthly", "yearly"}
_VALID_NDAYS = {"mo", "tu", "we", "th", "fr", "sa", "su"}

NEGATIVE_OFFSET_PATTERN = re.compile(
    r"^-P(?:\d+Y)?(?:\d+M)?(?:\d+W)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$"
)


def validate_priority(value: int) -> int:
    """Validate task priority (0-9).

    0 means undefined; 1 is highest; 9 is lowest.

    Raises:
        ValidationError: If outside 0-9.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(
            f"priority must be an integer, got {type(value).__name__}"
        )
    if value < 0 or value > 9:
        raise ValidationError(
            f"priority must be between 0 and 9 (got {value}). "
            "0 = undefined, 1 = highest, 9 = lowest."
        )
    return value


_GOOGLE_COLOR_IDS = frozenset(str(i) for i in range(1, 12))


def validate_google_color_id(value: str) -> str:
    """Validate a Google Calendar color ID ('1' through '11')."""
    if value not in _GOOGLE_COLOR_IDS:
        raise ValidationError("google_color_id must be a string '1' through '11'")
    return value


def validate_progress(value: str) -> str:
    """Validate task progress status string."""
    if value not in _VALID_TASK_PROGRESS:
        raise ValidationError(
            f"Invalid progress '{value}'. "
            f"Must be one of: {sorted(_VALID_TASK_PROGRESS)}"
        )
    return value


def validate_alert_offset(value: str) -> str:
    """Validate an alert offset like '-PT15M' (negative ISO 8601 duration).

    Alerts fire before the event start, so offsets must be negative.
    """
    if not value:
        raise ValidationError("alert offset cannot be empty")
    if not NEGATIVE_OFFSET_PATTERN.match(value):
        raise ValidationError(
            f"Invalid alert offset: '{value}'. "
            "Use a negative ISO 8601 duration (e.g., '-PT15M' for 15 minutes before, "
            "'-PT1H' for 1 hour before, '-P1D' for 1 day before)."
        )
    return value


def validate_recurrence_rule(rule: dict) -> None:
    """Validate the shape of a single recurrence rule dict.

    Expected keys: frequency (required), interval (optional, default 1),
    by_day (optional list of two-letter weekday codes).
    """
    if not isinstance(rule, dict):
        raise ValidationError(
            f"recurrence rule must be a dict, got {type(rule).__name__}"
        )

    frequency = rule.get("frequency")
    if not frequency:
        raise ValidationError("recurrence rule is missing required 'frequency'")
    if frequency not in _VALID_RECURRENCE_FREQUENCIES:
        raise ValidationError(
            f"Invalid recurrence frequency '{frequency}'. "
            f"Must be one of: {sorted(_VALID_RECURRENCE_FREQUENCIES)}"
        )

    interval = rule.get("interval", 1)
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
        raise ValidationError(
            f"recurrence rule 'interval' must be a positive integer (got {interval!r})"
        )

    by_day = rule["by_day"] if "by_day" in rule else rule.get("byDay")
    if by_day is not None:
        if not isinstance(by_day, list) or not by_day:
            raise ValidationError("'by_day' must be a non-empty list of weekday codes")
        for day in by_day:
            day_code = (
                day
                if isinstance(day, str)
                else day.get("day")
                if isinstance(day, dict)
                else None
            )
            if day_code not in _VALID_NDAYS:
                raise ValidationError(
                    f"Invalid weekday code '{day_code}'. "
                    f"Use two-letter lowercase codes: {sorted(_VALID_NDAYS)}"
                )


def validate_event_window_bound(value: str, field_name: str) -> datetime:
    """Validate and parse an event listing window bound.

    Accepts ISO 8601 timestamps with ``Z`` or a numeric offset (e.g.,
    ``2023-03-01T00:00:00Z``, ``2023-03-01T00:00:00-06:00``), or bare
    ``YYYY-MM-DDTHH:mm:ss`` strings (interpreted using ``time_zone`` or UTC).
    """
    if not value:
        raise ValidationError(f"'{field_name}' cannot be empty")
    if not EVENT_WINDOW_BOUND_PATTERN.match(value):
        raise ValidationError(
            f"Invalid {field_name} format: '{value}'. "
            "Expected ISO 8601 format such as '2023-03-01T00:00:00Z', "
            "'2023-03-01T00:00:00-06:00', or '2023-03-01T00:00:00' with time_zone."
        )
    try:
        return datetime.fromisoformat(value)
    except ValueError as e:
        raise ValidationError(f"Invalid {field_name} datetime '{value}': {e}") from e


def _validate_utc_bounds(
    start_dt: datetime,
    end_dt: datetime,
    raw_start: str,
    raw_end: str,
    max_days: int = 180,
) -> None:
    """Validate ordering and maximum span for two UTC-normalized datetimes."""
    if end_dt <= start_dt:
        raise ValidationError(f"'end' ({raw_end}) must be after 'start' ({raw_start})")

    days_diff = (end_dt - start_dt).days
    if days_diff > max_days:
        raise ValidationError(
            f"Date range too large: {days_diff} days. "
            f"Maximum allowed is {max_days} days (~6 months). "
            f"The Morgen API recommends retrieving no more than 2 months at a time."
        )


def _resolve_named_zone_bound(
    dt: datetime,
    raw: str,
    field_name: str,
    time_zone: str,
    zone: ZoneInfo,
) -> datetime:
    """Convert a naive wall time in a named IANA zone to UTC, rejecting DST gaps/folds."""
    utc0 = dt.replace(tzinfo=zone, fold=0).astimezone(UTC)
    utc1 = dt.replace(tzinfo=zone, fold=1).astimezone(UTC)
    roundtrip0 = utc0.astimezone(zone).replace(tzinfo=None)
    roundtrip1 = utc1.astimezone(zone).replace(tzinfo=None)
    if roundtrip0 != dt or roundtrip1 != dt:
        raise ValidationError(
            f"'{field_name}' ('{raw}') does not exist in timezone '{time_zone}' "
            "(daylight saving transition gap)."
        )
    if utc0 != utc1:
        raise ValidationError(
            f"'{field_name}' ('{raw}') is ambiguous in timezone '{time_zone}' "
            "(occurs twice during daylight saving fall-back). "
            "Provide an explicit UTC offset or 'Z' instead."
        )
    return utc0


def resolve_event_window(
    start: str,
    end: str,
    time_zone: str | None = None,
    max_days: int = 180,
) -> tuple[str, str]:
    """Validate an event listing window and normalize both bounds to UTC ``...Z``.

    Accepts explicit offsets (``Z`` or ``±HH:MM``) on ``start``/``end``, or bare
    ``YYYY-MM-DDTHH:mm:ss`` bounds interpreted in ``time_zone`` (defaulting to UTC
    when ``time_zone`` is omitted).
    """
    validate_timezone(time_zone)
    start_dt = validate_event_window_bound(start, "start")
    end_dt = validate_event_window_bound(end, "end")

    if (start_dt.tzinfo is None) != (end_dt.tzinfo is None):
        raise ValidationError(
            "Do not mix timezone-aware and naive bounds for 'start' and 'end'."
        )

    if start_dt.tzinfo is not None and time_zone is not None:
        raise ValidationError(
            "Do not specify 'time_zone' when 'start'/'end' already include a 'Z' or numeric offset."
        )

    if start_dt.tzinfo is not None:
        start_utc = start_dt.astimezone(UTC)
        end_utc = end_dt.astimezone(UTC)
    elif time_zone is not None:
        source_tz = ZoneInfo(time_zone)
        start_utc = _resolve_named_zone_bound(
            start_dt, start, "start", time_zone, source_tz
        )
        end_utc = _resolve_named_zone_bound(end_dt, end, "end", time_zone, source_tz)
    else:
        start_utc = start_dt.replace(tzinfo=UTC)
        end_utc = end_dt.replace(tzinfo=UTC)

    _validate_utc_bounds(start_utc, end_utc, start, end, max_days=max_days)
    return (
        start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def validate_date_range(start: str, end: str, max_days: int = 180) -> None:
    """Validate that a date range is valid and within limits.

    Args:
        start: Start datetime in ISO 8601 format (bare or with offset/Z).
        end: End datetime in ISO 8601 format (bare or with offset/Z).
        max_days: Maximum allowed range in days (default: 180 = ~6 months).

    Raises:
        ValidationError: If the range is invalid.
    """
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError as e:
        raise ValidationError(f"Cannot parse date range: {e}") from e

    if (start_dt.tzinfo is None) != (end_dt.tzinfo is None):
        raise ValidationError(
            "Do not mix timezone-aware and naive bounds for 'start' and 'end'."
        )

    if start_dt.tzinfo is not None:
        start_dt = start_dt.astimezone(UTC)
        end_dt = end_dt.astimezone(UTC)

    _validate_utc_bounds(start_dt, end_dt, start, end, max_days=max_days)
