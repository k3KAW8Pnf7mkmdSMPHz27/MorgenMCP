# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

```bash
uv sync --all-extras                    # Install dependencies
echo "MORGEN_API_KEY=..." > .env        # Configure API key (loaded automatically)
uv run morgenmcp                        # Run server
uv run pytest                           # Run all tests (excludes integration)
uv run pytest tests/test_tools.py::TestCreateEvent -v  # Run specific test class
uv run pytest tests/test_integration.py -v -s -m integration  # Run live API tests
uv run ruff check .                     # Lint code
uv run ruff format .                    # Format code
pre-commit install                      # Set up git hooks (once)
```

## Local Debugging

```bash
npx @modelcontextprotocol/inspector uv run morgenmcp
```
Opens Inspector UI at http://localhost:6274 for testing tools.

## Architecture

FastMCP-based MCP server wrapping the Morgen calendar API (https://api.morgen.so/v3/).

- **`server.py`** - Entry point with `@mcp.tool()` decorators delegating to tools modules
- **`client.py`** - Async HTTP client; global instance via `get_client()`
- **`models.py`** - Pydantic models with `Field(alias="...")` for camelCase API mapping
- **`validators.py`** - Input validation (datetime, duration, timezone, email, color)
- **`tools/`** - Tool implementations (`calendars.py`, `events.py`)

### Patterns

- Tools return `{"success": True, ...}` or `{"error": "...", "status_code": N}` or `{"error": "...", "validation_error": True}`
- Datetime fields use LocalDateTime format (`2023-03-01T10:00:00`) - no Z suffix; timezone is separate
- `EventCreateResponse` has nested structure: `response.event.id`, not `response.id`

### Morgen API ID Structure

IDs are base64-encoded JSON arrays with embedded relationships:

- **Account ID**: MongoDB ObjectId (24 hex chars)
  - `"507f1f77bcf86cd799439011"`

- **Calendar ID**: `base64([accountId, calendarEmail])`
  - `"WyI1MDdmMWY3N2JjZjg2Y2Q3OTk0MzkwMTEiLCJ1c2VyQGV4YW1wbGUuY29tIl0"`
  - Contains account ID at index 0

- **Event ID**: `base64([calendarEmail, eventUid, accountId])`
  - `"WyJ1c2VyQGV4YW1wbGUuY29tIiwiZXZ0XzEyMzQ1Njc4OTAiLCI1MDdmMWY3N2JjZjg2Y2Q3OTk0MzkwMTEiXQ"`
  - Account ID at index 2, calendar email at index 0
  - Calendar ID can be reconstructed: `base64([accountId, calendarEmail])`

This allows deriving account_id and calendar_id from event_id without caching.

### Virtual IDs

Tools expose 7-character Base64url virtual IDs (e.g., `aB-9xZ_`) instead of raw Morgen IDs for token efficiency. The `id_registry` module handles mapping between virtual and real IDs. Character set: `A-Za-z0-9-_`.

### Testing

- **Tool tests** (`test_tools.py`): Mock via `patch("morgenmcp.tools.*.get_client")`
- **Client tests** (`test_client.py`): Mock HTTP via `@respx.mock` decorator on test methods
- **Integration tests** (`test_integration.py`): Hit real API, excluded from CI via pytest marker

## Versioning & Release

Versions are managed via git tags. No build step required.

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Users reference tags in their MCP client config: `git+https://github.com/k3KAW8Pnf7mkmdSMPHz27/MorgenMCP@v0.1.0`

## API Docs

See `docs/morgen-dev-docs/` submodule (MDX files).
