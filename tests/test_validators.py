"""Tests for input validators."""

from zoneinfo import available_timezones

import pytest

from morgenmcp.validators import (
    ValidationError,
    resolve_event_window,
    validate_alert_offset,
    validate_date_range,
    validate_duration,
    validate_email,
    validate_free_busy_status,
    validate_google_color_id,
    validate_hex_color,
    validate_local_datetime,
    validate_priority,
    validate_privacy,
    validate_progress,
    validate_recurrence_rule,
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

    def test_windows_missing_timezones_simulation(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Simulate Windows environment without tzdata where available_timezones() is empty.

        This characterises the failure mode reported in #1 — it does *not*
        verify the fix. With the tz database missing, every IANA name is
        rejected, valid or not. The guard against that regressing is
        ``test_tzdata_supplies_iana_database`` below, which asserts the
        database is actually populated at runtime.
        """
        monkeypatch.setattr("morgenmcp.validators._VALID_TIMEZONES", None)
        monkeypatch.setattr("morgenmcp.validators.available_timezones", lambda: set())

        with pytest.raises(ValidationError) as exc_info:
            validate_timezone("America/New_York")

        assert "Invalid timezone: 'America/New_York'" in str(exc_info.value)

    def test_tzdata_supplies_iana_database(self):
        """The IANA database must be populated on every supported platform.

        This is the actual regression guard for #1. Windows ships no system tz
        database, so without the ``tzdata`` dependency ``available_timezones()``
        is empty there and validation rejects every real timezone. Unlike the
        simulation above, this fails on a bare Windows runner if that
        dependency is ever dropped — which is what the multi-OS CI matrix is
        for.
        """
        zones = available_timezones()

        assert zones, (
            "available_timezones() is empty — is the tzdata dependency installed?"
        )
        for name in ("America/New_York", "Europe/Berlin", "UTC"):
            assert name in zones, f"{name} missing from the IANA database"
            assert validate_timezone(name) == name


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
        validate_date_range("2023-03-01T00:00:00", "2023-04-01T00:00:00", max_days=60)


class TestResolveEventWindow:
    """Tests for resolve_event_window."""

    def test_bare_bounds_default_to_utc(self):
        assert resolve_event_window("2026-11-14T12:00:00", "2026-11-14T16:00:00") == (
            "2026-11-14T12:00:00Z",
            "2026-11-14T16:00:00Z",
        )

    def test_z_suffix_bounds_accepted(self):
        assert resolve_event_window("2026-11-14T18:00:00Z", "2026-11-14T22:00:00Z") == (
            "2026-11-14T18:00:00Z",
            "2026-11-14T22:00:00Z",
        )

    def test_numeric_offsets_converted_to_utc(self):
        assert resolve_event_window(
            "2026-11-14T12:00:00-06:00", "2026-11-14T16:00:00-06:00"
        ) == ("2026-11-14T18:00:00Z", "2026-11-14T22:00:00Z")

    def test_time_zone_converts_bare_bounds_to_utc_cst_and_cdt(self):
        # Nov 14, 2026 is CST (UTC-6)
        assert resolve_event_window(
            "2026-11-14T12:00:00",
            "2026-11-14T16:00:00",
            time_zone="America/Chicago",
        ) == ("2026-11-14T18:00:00Z", "2026-11-14T22:00:00Z")
        # Jul 15, 2026 is CDT (UTC-5)
        assert resolve_event_window(
            "2026-07-15T12:00:00",
            "2026-07-15T16:00:00",
            time_zone="America/Chicago",
        ) == ("2026-07-15T17:00:00Z", "2026-07-15T21:00:00Z")

    def test_rejects_mixing_aware_and_naive_bounds(self):
        with pytest.raises(ValidationError, match="Do not mix"):
            resolve_event_window("2026-11-14T12:00:00Z", "2026-11-14T16:00:00")
        with pytest.raises(ValidationError, match="Do not mix"):
            resolve_event_window("2026-11-14T12:00:00", "2026-11-14T16:00:00-06:00")

    def test_rejects_explicit_offset_combined_with_time_zone(self):
        with pytest.raises(ValidationError, match="Do not specify 'time_zone'"):
            resolve_event_window(
                "2026-11-14T12:00:00-06:00",
                "2026-11-14T16:00:00-06:00",
                time_zone="America/Chicago",
            )

    def test_rejects_bad_format_and_invalid_calendar_date(self):
        with pytest.raises(ValidationError, match="Invalid start format"):
            resolve_event_window("2026-11-14", "2026-11-15T00:00:00")
        with pytest.raises(ValidationError, match="Invalid start datetime"):
            resolve_event_window("2026-13-01T00:00:00Z", "2026-13-02T00:00:00Z")

    @pytest.mark.parametrize(
        "bad_bound",
        [
            "2026-11-14T12:00:00+00:60",
            "2026-11-14T12:00:00-06:99",
            "2026-11-14T12:00:00+24:00",
        ],
    )
    def test_rejects_out_of_range_offset_components(self, bad_bound):
        with pytest.raises(ValidationError, match="Invalid start format"):
            resolve_event_window(bad_bound, "2026-11-14T16:00:00+00:00")

    def test_rejects_nonexistent_dst_spring_forward_bound(self):
        with pytest.raises(ValidationError, match="does not exist"):
            resolve_event_window(
                "2026-03-08T02:15:00",
                "2026-03-08T02:45:00",
                time_zone="America/Chicago",
            )

    def test_rejects_ambiguous_dst_fall_back_bound_and_accepts_explicit_offset(self):
        with pytest.raises(ValidationError, match="ambiguous"):
            resolve_event_window(
                "2026-11-01T01:15:00",
                "2026-11-01T04:00:00",
                time_zone="America/Chicago",
            )
        assert resolve_event_window(
            "2026-11-01T01:15:00-05:00", "2026-11-01T01:15:00-06:00"
        ) == ("2026-11-01T06:15:00Z", "2026-11-01T07:15:00Z")


class TestValidatePriority:
    def test_valid_range(self):
        for p in range(0, 10):
            assert validate_priority(p) == p

    def test_too_low(self):
        with pytest.raises(ValidationError):
            validate_priority(-1)

    def test_too_high(self):
        with pytest.raises(ValidationError):
            validate_priority(10)

    def test_non_integer(self):
        with pytest.raises(ValidationError):
            validate_priority("3")  # type: ignore[arg-type]

    def test_bool_rejected(self):
        with pytest.raises(ValidationError):
            validate_priority(True)  # type: ignore[arg-type]


class TestValidateProgress:
    def test_valid(self):
        for p in ["needs-action", "in-process", "completed", "failed", "cancelled"]:
            assert validate_progress(p) == p

    def test_invalid(self):
        with pytest.raises(ValidationError):
            validate_progress("done")


class TestEnumAndTypeGuards:
    """Wrong-typed input gets a field-specific error, never a Python TypeError."""

    def test_google_color_id(self):
        assert validate_google_color_id("11") == "11"
        for bad in ("0", "12", "", [], {}, 5, None):
            with pytest.raises(ValidationError, match="google_color_id must be"):
                validate_google_color_id(bad)  # type: ignore[arg-type]

    def test_privacy(self):
        for ok in ("public", "private", "secret"):
            assert validate_privacy(ok) == ok
        for bad in ("typo", "", [], 5):
            with pytest.raises(ValidationError, match="privacy must be one of"):
                validate_privacy(bad)  # type: ignore[arg-type]

    def test_free_busy_status(self):
        for ok in ("free", "busy"):
            assert validate_free_busy_status(ok) == ok
        for bad in ("typo", "", [], 5):
            with pytest.raises(
                ValidationError, match="free_busy_status must be one of"
            ):
                validate_free_busy_status(bad)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("func", "bad"),
        [
            (validate_local_datetime, 5),
            (validate_local_datetime, ["2023-03-01T10:00:00"]),
            (validate_duration, 5),
            (validate_duration, ["PT1H"]),
            (validate_timezone, 5),
            (validate_timezone, ["UTC"]),
            (validate_alert_offset, 5),
            (validate_alert_offset, ["-PT15M"]),
        ],
    )
    def test_non_string_rejected(self, func, bad):
        with pytest.raises(ValidationError, match="must be a string"):
            func(bad)

    def test_recurrence_frequency_and_day_types(self):
        with pytest.raises(ValidationError, match="Invalid recurrence frequency"):
            validate_recurrence_rule({"frequency": ["daily"]})
        with pytest.raises(ValidationError, match="Invalid weekday code"):
            validate_recurrence_rule(
                {"frequency": "weekly", "by_day": [{"day": ["mo"]}]}
            )


class TestValidateAlertOffset:
    def test_valid_minutes(self):
        assert validate_alert_offset("-PT15M") == "-PT15M"

    def test_valid_hours(self):
        assert validate_alert_offset("-PT1H") == "-PT1H"

    def test_valid_day(self):
        assert validate_alert_offset("-P1D") == "-P1D"

    def test_rejects_positive(self):
        with pytest.raises(ValidationError):
            validate_alert_offset("PT15M")

    def test_rejects_empty(self):
        with pytest.raises(ValidationError):
            validate_alert_offset("")

    def test_rejects_garbage(self):
        with pytest.raises(ValidationError):
            validate_alert_offset("-15 minutes")


class TestValidateRecurrenceRule:
    def test_minimal(self):
        validate_recurrence_rule({"frequency": "weekly"})

    def test_with_interval_and_byday(self):
        validate_recurrence_rule(
            {"frequency": "weekly", "interval": 2, "by_day": ["mo", "we"]}
        )

    def test_camel_case_byday(self):
        validate_recurrence_rule({"frequency": "weekly", "byDay": [{"day": "fr"}]})

    def test_missing_frequency(self):
        with pytest.raises(ValidationError, match="frequency"):
            validate_recurrence_rule({})

    def test_invalid_frequency(self):
        with pytest.raises(ValidationError, match="frequency"):
            validate_recurrence_rule({"frequency": "fortnightly"})

    def test_invalid_interval(self):
        with pytest.raises(ValidationError, match="interval"):
            validate_recurrence_rule({"frequency": "daily", "interval": 0})

    def test_invalid_byday(self):
        with pytest.raises(ValidationError, match="weekday"):
            validate_recurrence_rule({"frequency": "weekly", "by_day": ["xx"]})

    def test_byday_must_be_list(self):
        with pytest.raises(ValidationError, match="non-empty"):
            validate_recurrence_rule({"frequency": "weekly", "by_day": []})

    def test_non_dict(self):
        with pytest.raises(ValidationError, match="dict"):
            validate_recurrence_rule(["weekly"])  # type: ignore[arg-type]
