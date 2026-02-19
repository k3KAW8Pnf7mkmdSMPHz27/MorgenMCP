# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

```bash
uv sync --all-extras                    # Install dependencies
echo "export MORGEN_API_KEY=..." > .envrc && direnv allow  # Configure API key
uv run morgenmcp                        # Run server
uv run pytest                           # Run all tests (excludes integration)
uv run pytest tests/test_tools.py::TestCreateEvent -v  # Run specific test class
uv run pytest tests/test_tools.py::TestCreateEvent::test_create_basic_event -v  # Run single test
uv run pytest tests/test_integration.py -v -s -m integration  # Run live API tests
uv run ruff check .                     # Lint code
uv run ruff format .                    # Format code
uv run pyright morgenmcp/               # Type check
pre-commit install                      # Set up git hooks (once)
```

## Local Debugging

```bash
npx @modelcontextprotocol/inspector uv run morgenmcp
```
Opens Inspector UI at http://localhost:6274 for testing tools.

## Architecture

FastMCP-based MCP server wrapping the Morgen calendar API (https://api.morgen.so/v3/).

- **`server.py`** - Entry point registering tools from tools modules. Tools are **not** decorated with `@mcp.tool()` on the function; instead, `server.py` uses `mcp.tool(name=..., tags=..., annotations=...)(func)` as a call expression. This decoupling means tool functions remain plain async functions importable for unit testing.
- **`client.py`** - Async HTTP client; global instance via `get_client()`. Auth header: `"Authorization": f"ApiKey {self.api_key}"` (not `Bearer`).
- **`models.py`** - Pydantic models using `Annotated[type, Field(alias="...")]` pattern. Base `MorgenModel` config: `validate_by_name=True, validate_by_alias=True`. Serialize with `model.model_dump(by_alias=True, exclude_none=True)`.
- **`validators.py`** - Input validation (datetime, duration, timezone, email, color)
- **`tools/`** - Tool implementations:
  - `accounts.py`, `calendars.py`, `events.py` - MCP tool functions
  - `id_registry.py` - Virtual ID ↔ real ID bidirectional mapping
  - `id_utils.py` - Extract account/calendar IDs from encoded Morgen IDs
  - `utils.py` - Shared helpers (`filter_none_values`, `handle_tool_errors`)

### Patterns

- Tools return `{"success": True, ...}` on success
- Tools raise `ToolError` (from `fastmcp.exceptions`) on failure — messages are always visible to LLMs
- `@handle_tool_errors` in `utils.py` converts ValidationError, MorgenAPIError, and unexpected exceptions to ToolError
- Batch operations return partial results with `{"deleted": [...], "failed": [...]}` — per-item failures are dict entries, not ToolError
- Datetime fields use LocalDateTime format (`2023-03-01T10:00:00`) - no Z suffix; timezone is separate
- `EventCreateResponse` has nested structure: `response.event.id`, not `response.id`
- **Timing fields constraint**: `update_event` and `batch_update_events` require all four timing fields (`start`, `duration`, `time_zone`, `is_all_day`) together or none — partial updates are rejected

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

Virtual IDs are **session-scoped** (module-level dicts, not persisted). Restarting the server loses all mappings. LLMs must call list tools (e.g., `list_calendars`, `list_events`) before using IDs in write operations.

### Testing

- **Tool tests** (`test_tools.py`): Mock via `patch("morgenmcp.tools.*.get_client")`
- **Client tests** (`test_client.py`): Mock HTTP via `@respx.mock` decorator on test methods
- **MCP protocol tests** (`test_mcp_server.py`): In-memory protocol-level tests using `fastmcp.Client(mcp)` — verifies tool registration, annotations, and end-to-end call flow
- **Integration tests** (`test_integration.py`): Hit real API, excluded from CI via pytest marker

### Environment

- Python `>= 3.14` (set in `pyproject.toml`)
- `fastmcp==3.0.0` — pinned to stable release

## Versioning & Release

Versions are managed via git tags. No build step required.

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Users reference tags in their MCP client config: `git+https://github.com/k3KAW8Pnf7mkmdSMPHz27/MorgenMCP@v0.1.0`

## Documentation Resources

Five documentation sources are available. Use them in combination to get accurate, up-to-date information.

| Source | URL / Path | What it covers |
|--------|-----------|----------------|
| **Morgen API** (online) | https://docs.morgen.so/ | Endpoints, parameters, schemas, changelog |
| **Morgen API** (local) | `docs/morgen-dev-docs/content/*.mdx` | Same content, readable offline. Use the `morgen-api-docs` agent for lookups |
| **FastMCP** (online) | https://gofastmcp.com/llms.txt | Server framework (latest version, requires network) |
| **FastMCP** (local) | `docs/fastmcp/docs/` | Same content, readable offline. Use the `fastmcp-docs` agent for lookups |
| **MCP Protocol** | https://modelcontextprotocol.io/llms.txt | Protocol spec: transports, tool schema, JSON-RPC messages |

- **Morgen docs submodule**: `f977d08` (updated automatically by SessionStart hook)
- **FastMCP docs submodule**: `v3.0.0` / `92f4c503` (updated automatically by SessionStart hook)

### How to use these sources

- **Before implementing or modifying any tool**, look up the relevant Morgen API endpoint in both the online docs and the local MDX files to confirm parameters, required fields, and response shapes. The online docs may be newer; the local submodule is version-pinned and always available.
- **For FastMCP patterns** (tool registration, return types, error handling, testing), use the `fastmcp-docs` agent — it searches `docs/fastmcp/docs/` (v3 only) and returns file paths, line numbers, and code examples. Fall back to `https://gofastmcp.com/llms.txt` if local docs are insufficient.
- **For MCP protocol questions** (transport, JSON-RPC, tool schema), fetch `https://modelcontextprotocol.io/llms.txt` first, then the relevant spec page.
- **Use the `morgen-api-docs` agent** (read-only) for Morgen API questions — it searches `docs/morgen-dev-docs/content/` and returns file paths, line numbers, and direct quotes. For cross-referencing, run it in parallel with a WebFetch of the online docs.
- **When adding a new tool or changing tool signatures**, check both FastMCP docs (for decorator/return-type patterns) and the MCP protocol spec (for schema requirements) to ensure compliance.
