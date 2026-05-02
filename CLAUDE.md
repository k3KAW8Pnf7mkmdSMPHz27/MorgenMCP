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
  - `accounts.py`, `calendars.py`, `events.py`, `tasks.py`, `tags.py` - MCP tool functions
  - `id_registry.py` - Virtual ID ↔ real ID bidirectional mapping with disk persistence
  - `id_utils.py` - Extract account/calendar IDs from encoded Morgen IDs (events/calendars only — task and tag IDs are opaque)
  - `utils.py` - Shared helpers (`filter_none_values`, `handle_tool_errors`, `build_alerts_dict`, `build_recurrence_rules`)

### Patterns

- Tools return `{"success": True, ...}` on success
- Tools raise `ToolError` (from `fastmcp.exceptions`) on failure — messages are always visible to LLMs
- `@handle_tool_errors` in `utils.py` converts ValidationError, MorgenAPIError, and unexpected exceptions to ToolError
- Batch operations return partial results with `{"deleted": [...], "failed": [...]}` — per-item failures are dict entries, not ToolError
- Datetime fields use LocalDateTime format (`2023-03-01T10:00:00`) - no Z suffix; timezone is separate
- `EventCreateResponse` has nested structure: `response.event.id`, not `response.id`
- **Timing fields constraint**: `update_event` and `batch_update_events` require all four timing fields (`start`, `duration`, `time_zone`, `is_all_day`) together or none — partial updates are rejected
- **Alerts**: Tools accept negative ISO 8601 offsets (e.g., `'-PT15M'`) and convert them to Morgen's base64-encoded alert ID format (`base64(JSON({a:'display',to:offset}))`). `alerts` and `use_default_alerts` are mutually exclusive.
- **Recurrence rules**: Accept simplified dicts `{frequency, interval, by_day}`; the `build_recurrence_rules` helper converts to JSCalendar `RecurrenceRule` objects.
- **Tags endpoint quirk**: `/tags/list` returns a bare JSON array, not the standard `{data: ...}` envelope — the client handles both shapes.
- **EventUpdateRequest.alerts** uses `dict[str, Alert | None]` to support patch-style removal (set entry to `None` to delete that alert). `EventCreateRequest.alerts` uses the same widened type for consistency at type-check time, even though create never accepts None values.

### Morgen API ID Structure

Calendar/event IDs are base64-encoded JSON arrays with embedded relationships:

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

**Tasks and tags use opaque IDs** — base64 strings (tasks) and UUIDs (tags) without embedded structure. They go through the same virtual-ID layer but require no extraction utilities.

### Virtual IDs

Tools expose 7-character Base64url virtual IDs (e.g., `aB-9xZ_`) instead of raw Morgen IDs for token efficiency. The `id_registry` module handles mapping between virtual and real IDs. Character set: `A-Za-z0-9-_`.

Virtual IDs are **deterministic** (`MD5(real_id)`) and **persisted to disk** via `py-key-value-aio`'s `FileTreeStore`. Reads are sync in-memory dict lookups; writes are fire-and-forget async write-through to the store. On startup, the server lifespan loads all persisted mappings into memory, so IDs survive server restarts without re-listing.

- **Storage location**: `~/Library/Application Support/morgenmcp/id_store/` (via `platformdirs.user_data_dir`)
- **Override**: Set `MORGENMCP_DATA_DIR` env var to use a custom directory
- **Graceful degradation**: If the store fails to initialize, the server continues with in-memory-only IDs (session-scoped)
- **Tests**: Persistence is disabled by an `autouse` conftest fixture (`set_store(None)`)

### Testing

- **Tool tests** (`test_tools.py`): Mock via `patch("morgenmcp.tools.*.get_client")`
- **Client tests** (`test_client.py`): Mock HTTP via `@respx.mock` decorator on test methods
- **MCP protocol tests** (`test_mcp_server.py`): In-memory protocol-level tests using `fastmcp.Client(mcp)` — verifies tool registration, annotations, and end-to-end call flow. Uses `MORGENMCP_DATA_DIR=tmp_path` to isolate the persistent store.
- **Persistence tests** (`test_id_persistence.py`): Tests FileTreeStore write-through and cross-session restore using real temp-dir-backed stores
- **Integration tests** (`test_integration.py`): Hit real API, excluded from CI via pytest marker

### Environment

- Python `>= 3.14` (set in `pyproject.toml`)
- `fastmcp>=3.2,<3.3` — pinned to 3.2.x patch range

## Versioning & Release

Versions are managed via git tags. No build step required.

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Users reference tags in their MCP client config: `git+https://github.com/k3KAW8Pnf7mkmdSMPHz27/MorgenMCP@v0.1.0`

## Documentation Resources

**IMPORTANT: Always use the local docs submodules as the primary source of truth.** They are version-pinned to match the exact dependency versions in this project. Online docs may describe newer or older API versions that do not match what this project uses. Only fall back to online docs when local docs are insufficient.

When spawning Explore agents, **always include this instruction in the prompt**: _"For Morgen API questions, search `docs/morgen-dev-docs/content/` first. For FastMCP questions, search `docs/fastmcp/docs/` first. These local docs match the pinned dependency versions and take priority over online sources."_

### Local docs (primary — version-pinned, always available)

| Source | Path | Agent | Covers |
|--------|------|-------|--------|
| **Morgen API** | `docs/morgen-dev-docs/content/*.mdx` | `morgen-api-docs` | Endpoints, parameters, schemas, changelog |
| **FastMCP** | `docs/fastmcp/docs/` | `fastmcp-docs` | Server framework: tools, context, auth, testing, deployment |

- **Morgen docs submodule**: `f977d08` (updated automatically by SessionStart hook)
- **FastMCP docs submodule**: `v3.2.4` / `7d760747` — matches `fastmcp>=3.2,<3.3` pin (updated automatically by SessionStart hook)

### Online docs (fallback only)

| Source | URL | When to use |
|--------|-----|-------------|
| **Morgen API** | https://docs.morgen.so/ | Only if local MDX files lack the endpoint or field you need |
| **FastMCP** | https://gofastmcp.com/llms.txt | Only if local docs under `docs/fastmcp/docs/` don't cover the topic |
| **MCP Protocol** | https://modelcontextprotocol.io/llms.txt | Protocol spec: transports, tool schema, JSON-RPC messages (no local copy) |

### Lookup rules

1. **Before implementing or modifying any tool**: Use the `morgen-api-docs` agent to look up the relevant Morgen API endpoint in the local MDX files. Confirm parameters, required fields, and response shapes. Only cross-reference online docs if the local result is incomplete.
2. **For FastMCP patterns** (tool registration, return types, error handling, testing): Use the `fastmcp-docs` agent — it searches `docs/fastmcp/docs/` and returns file paths, line numbers, and code examples. These docs match the installed FastMCP version exactly.
3. **For MCP protocol questions** (transport, JSON-RPC, tool schema): Fetch `https://modelcontextprotocol.io/llms.txt` first, then the relevant spec page (no local copy exists).
4. **When adding a new tool or changing tool signatures**: Check both FastMCP local docs (for decorator/return-type patterns) and the MCP protocol spec (for schema requirements) to ensure compliance.
5. **When spawning any agent** (Explore, Plan, or general-purpose) that may need API or framework information: Include the local doc paths and agent names in the prompt so the subagent searches them directly rather than guessing or using online sources.
