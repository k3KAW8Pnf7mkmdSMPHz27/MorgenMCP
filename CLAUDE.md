# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync --all-extras

# Run the MCP server
export MORGEN_API_KEY="your_api_key"
uv run morgenmcp

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_models.py

# Run a specific test
uv run pytest tests/test_tools.py::TestCreateEvent::test_create_event_success -v
```

## Architecture

This is a FastMCP-based MCP server that wraps the Morgen calendar API (https://api.morgen.so/v3/).

### Module Structure

- **`server.py`** - FastMCP server entry point. Registers MCP tools with `@mcp.tool()` decorators that delegate to the tools modules.
- **`client.py`** - Async HTTP client (`MorgenClient`) for Morgen API. Handles authentication, rate limiting, and error responses. Uses a global client instance via `get_client()`.
- **`models.py`** - Pydantic models based on JSCalendar spec. Key models: `Calendar`, `Event`, `EventCreateRequest`, `EventUpdateRequest`. All use `Field(alias="...")` for API field mapping.
- **`tools/calendars.py`** - Calendar tools: `list_calendars`, `update_calendar_metadata`
- **`tools/events.py`** - Event tools: `list_events`, `create_event`, `update_event`, `delete_event`

### Key Patterns

- All tools return dicts with either `{"success": True, ...}` or `{"error": "...", "status_code": N}`
- Pydantic models use `populate_by_name=True` and `by_alias=True` for API serialization
- Tests mock the client via `patch("morgenmcp.tools.*.get_client")`

### API Documentation

The `docs/morgen-dev-docs/` submodule contains the Morgen API documentation (MDX files). Update the submodule when the API changes.
