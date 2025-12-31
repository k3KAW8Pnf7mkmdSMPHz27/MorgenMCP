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
