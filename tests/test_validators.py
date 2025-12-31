"""Tests for input validators."""

import pytest

from morgenmcp.validators import (
    ValidationError,
    validate_date_range,
    validate_duration,
    validate_email,
    validate_hex_color,
    validate_local_datetime,
    validate_timezone,
)


class TestValidateLocalDatetime:
    """Tests for validate_local_datetime."""

    def test_valid_datetime(self):
        """Valid LocalDateTime format should pass."""
        assert validate_local_datetime("2023-03-01T10:00:00") == "2023-03-01T10:00:00"
        assert validate_local_datetime("2023-12-31T23:59:59") == "2023-12-31T23:59:59"
        assert validate_local_datetime("2024-01-01T00:00:00") == "2024-01-01T00:00:00"

    def test_rejects_z_suffix(self):
        """Datetime with Z suffix should be rejected with helpful message."""
        with pytest.raises(ValidationError) as exc_info:
            validate_local_datetime("2023-03-01T10:00:00Z")

        assert "Remove the 'Z' suffix" in str(exc_info.value)
        assert "LocalDateTime format" in str(exc_info.value)

    def test_rejects_positive_offset(self):
        """Datetime with positive timezone offset should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_local_datetime("2023-03-01T10:00:00+02:00")

        assert "Remove the timezone offset" in str(exc_info.value)

    def test_rejects_negative_offset(self):
        """Datetime with negative timezone offset should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_local_datetime("2023-03-01T10:00:00-05:00")

        assert "Remove the timezone offset" in str(exc_info.value)

    def test_rejects_invalid_format(self):
        """Invalid datetime format should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_local_datetime("2023/03/01 10:00:00")

        assert "Expected LocalDateTime format" in str(exc_info.value)

    def test_rejects_empty(self):
        """Empty string should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_local_datetime("")

        assert "cannot be empty" in str(exc_info.value)

    def test_custom_field_name(self):
        """Custom field name should appear in error message."""
        with pytest.raises(ValidationError) as exc_info:
            validate_local_datetime("invalid", field_name="start_time")

        assert "start_time" in str(exc_info.value)


class TestValidateDuration:
    """Tests for validate_duration."""

    def test_valid_hours(self):
        """Duration in hours should pass."""
        assert validate_duration("PT1H") == "PT1H"
        assert validate_duration("PT24H") == "PT24H"

    def test_valid_minutes(self):
        """Duration in minutes should pass."""
        assert validate_duration("PT30M") == "PT30M"
        assert validate_duration("PT90M") == "PT90M"

    def test_valid_combined(self):
        """Combined hours and minutes should pass."""
        assert validate_duration("PT1H30M") == "PT1H30M"
        assert validate_duration("PT2H45M") == "PT2H45M"

    def test_valid_days(self):
        """Duration in days should pass."""
        assert validate_duration("P1D") == "P1D"
        assert validate_duration("P7D") == "P7D"

    def test_valid_complex(self):
        """Complex duration patterns should pass."""
        assert validate_duration("P1DT2H30M") == "P1DT2H30M"
        assert validate_duration("PT1H30M45S") == "PT1H30M45S"

    def test_rejects_invalid_format(self):
        """Invalid duration format should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_duration("1 hour")

        assert "ISO 8601 duration format" in str(exc_info.value)
        assert "PT1H" in str(exc_info.value)  # Example in error message

    def test_rejects_empty_duration(self):
        """Empty duration 'P' or 'PT' should be rejected."""
        with pytest.raises(ValidationError):
            validate_duration("P")

        with pytest.raises(ValidationError):
            validate_duration("PT")

    def test_rejects_empty_string(self):
        """Empty string should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_duration("")

        assert "cannot be empty" in str(exc_info.value)


class TestValidateTimezone:
    """Tests for validate_timezone."""

    def test_valid_timezones(self):
        """Valid IANA timezones should pass."""
        assert validate_timezone("Europe/Berlin") == "Europe/Berlin"
        assert validate_timezone("America/New_York") == "America/New_York"
        assert validate_timezone("Asia/Tokyo") == "Asia/Tokyo"
        assert validate_timezone("UTC") == "UTC"

    def test_none_allowed(self):
        """None should be allowed for floating events."""
        assert validate_timezone(None) is None

    def test_rejects_abbreviations(self):
        """Timezone abbreviations should be rejected with suggestions."""
        # Note: EST is actually in zoneinfo (legacy), but PST is not
        with pytest.raises(ValidationError) as exc_info:
            validate_timezone("PST")

        assert "America/Los_Angeles" in str(exc_info.value)

    def test_rejects_gmt_offset(self):
        """GMT offset format should be rejected with suggestions."""
        with pytest.raises(ValidationError) as exc_info:
            validate_timezone("GMT+2")

        assert "UTC" in str(exc_info.value) or "Etc/GMT" in str(exc_info.value)

    def test_rejects_invalid(self):
        """Invalid timezone should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_timezone("Not/A/Timezone")

        assert "IANA timezone format" in str(exc_info.value)

    def test_rejects_empty_string(self):
        """Empty string should be rejected (use None instead)."""
        with pytest.raises(ValidationError) as exc_info:
            validate_timezone("")

        assert "cannot be an empty string" in str(exc_info.value)


class TestValidateEmail:
    """Tests for validate_email."""

    def test_valid_emails(self):
        """Valid email addresses should pass."""
        assert validate_email("user@example.com") == "user@example.com"
        assert validate_email("test.user@domain.org") == "test.user@domain.org"
        assert validate_email("name+tag@company.co.uk") == "name+tag@company.co.uk"

    def test_rejects_missing_at(self):
        """Email without @ should be rejected."""
        with pytest.raises(ValidationError):
            validate_email("userexample.com")

    def test_rejects_missing_domain(self):
        """Email without domain should be rejected."""
        with pytest.raises(ValidationError):
            validate_email("user@")

    def test_rejects_empty(self):
        """Empty string should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_email("")

        assert "cannot be empty" in str(exc_info.value)


class TestValidateHexColor:
    """Tests for validate_hex_color."""

    def test_valid_colors(self):
        """Valid hex colors should pass."""
        assert validate_hex_color("#FF5733") == "#FF5733"
        assert validate_hex_color("#7EF2FC") == "#7EF2FC"
        assert validate_hex_color("#000000") == "#000000"
        assert validate_hex_color("#ffffff") == "#ffffff"

    def test_rejects_without_hash(self):
        """Color without # prefix should be rejected."""
        with pytest.raises(ValidationError):
            validate_hex_color("FF5733")

    def test_rejects_short_format(self):
        """Short hex format (#RGB) should be rejected."""
        with pytest.raises(ValidationError):
            validate_hex_color("#F53")

    def test_rejects_color_names(self):
        """Color names should be rejected."""
        with pytest.raises(ValidationError):
            validate_hex_color("red")

    def test_rejects_invalid_hex(self):
        """Invalid hex characters should be rejected."""
        with pytest.raises(ValidationError):
            validate_hex_color("#GGGGGG")

    def test_rejects_empty(self):
        """Empty string should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_hex_color("")

        assert "cannot be empty" in str(exc_info.value)


class TestValidateDateRange:
    """Tests for validate_date_range."""

    def test_valid_range(self):
        """Valid date range should pass."""
        # No exception means success
        validate_date_range("2023-03-01T00:00:00", "2023-03-15T00:00:00")

    def test_rejects_end_before_start(self):
        """End before start should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_date_range("2023-03-15T00:00:00", "2023-03-01T00:00:00")

        assert "must be after" in str(exc_info.value)

    def test_rejects_equal_dates(self):
        """Equal start and end should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_date_range("2023-03-01T00:00:00", "2023-03-01T00:00:00")

        assert "must be after" in str(exc_info.value)

    def test_rejects_range_too_large(self):
        """Range exceeding max_days should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_date_range("2023-01-01T00:00:00", "2023-12-31T00:00:00")

        assert "too large" in str(exc_info.value)
        assert "6 months" in str(exc_info.value)

    def test_custom_max_days(self):
        """Custom max_days should be respected."""
        # 30 day range should fail with max_days=7
        with pytest.raises(ValidationError):
            validate_date_range(
                "2023-03-01T00:00:00", "2023-04-01T00:00:00", max_days=7
            )

        # But pass with max_days=60
        validate_date_range(
            "2023-03-01T00:00:00", "2023-04-01T00:00:00", max_days=60
        )
