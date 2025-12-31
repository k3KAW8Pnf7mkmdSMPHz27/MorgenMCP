"""Shared pytest fixtures and helpers."""


def assert_api_error(result: dict, status_code: int) -> None:
    """Assert that result contains an API error with the expected status code."""
    assert "error" in result
    assert result["status_code"] == status_code


def assert_validation_error(result: dict) -> None:
    """Assert that result contains a validation error."""
    assert "error" in result
    assert result.get("validation_error") is True
