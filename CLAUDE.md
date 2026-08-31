# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

The import above pulls in `AGENTS.md` — the harness-agnostic contributor guide (environment setup, base lint/format/typecheck/test commands, code conventions, scope and safety rules) shared with any other coding-agent tool working in this repo. Edit that file, not this section, when those base commands or conventions change; the two must not drift.

## Quick Reference (Claude Code additions)

Commands specific to working in this repo through Claude Code — beyond the base set in `AGENTS.md`:

```bash
mise trust && mise set --file mise.local.toml MORGEN_API_KEY=...  # Configure API key
uv run morgenmcp                        # Run server
uv run morgenmcp --read-only            # Run server with only the 6 read tools (also: MORGENMCP_READ_ONLY=1)
uv run pytest tests/test_tools.py::TestCreateEvent -v  # Run specific test class
uv run pytest tests/test_tools.py::TestCreateEvent::test_create_basic_event -v  # Run single test
uv run pytest tests/test_integration.py -v -s -m integration  # Run live API tests
```

## Local Debugging

```bash
npx @modelcontextprotocol/inspector uv run morgenmcp
```
Opens Inspector UI at http://localhost:6274 for testing tools.

## Architecture

FastMCP-based MCP server wrapping the Morgen calendar API (https://api.morgen.so/v3/).

- **`server.py`** - Entry point registering tools and resources. Tools and resources are **not** decorated on the function; instead, `server.py` uses `mcp.tool(name=..., ...)(func)` and `mcp.resource(uri, ...)(func)` as call expressions. This decoupling means tool/resource functions remain plain async functions importable for unit testing.
- **`client.py`** - Async HTTP client; global instance via `get_client()`. Auth header: `"Authorization": f"ApiKey {self.api_key}"` (not `Bearer`).
- **`models.py`** - Pydantic models using `Annotated[type, Field(alias="...")]` pattern. Base `MorgenModel` config: `validate_by_name=True, validate_by_alias=True`. Serialize with `model.model_dump(by_alias=True, exclude_none=True)`.
- **`validators.py`** - Input validation (datetime, duration, timezone, email, color)
- **`resources.py`** - MCP resource handlers under the `morgen://` URI scheme. Read-only — writes still go through tools. Static URIs (`morgen://server`, `morgen://accounts`, `morgen://calendars`, `morgen://events/today`, `morgen://events/this-week`, `morgen://events/upcoming`, `morgen://tasks`, `morgen://tasks/today`, `morgen://tags`) and templates (`morgen://account/{account_id}`, `morgen://calendar/{calendar_id}`, `morgen://calendar/{calendar_id}/events`). All return `application/json` strings; IDs are virtual, identical to tool output. Renaming any URI is a breaking contract change for saved client chats.
- **`tools/`** - Tool implementations:
  - `accounts.py`, `calendars.py`, `events.py`, `tasks.py`, `tags.py` - MCP tool functions
  - `id_registry.py` - Virtual ID ↔ real ID bidirectional mapping with disk persistence
  - `id_utils.py` - Extract account/calendar IDs from encoded Morgen IDs (events/calendars only — task and tag IDs are opaque)
  - `utils.py` - Shared helpers (`filter_none_values`, `handle_tool_errors`, `build_alerts_dict`, `build_recurrence_rules`)

### Patterns

- **Response caching**: `server.py` registers a `ResponseCachingMiddleware` with a 60s in-memory TTL. It caches an explicit allowlist of read-only tools (`morgen_list_*`, `morgen_get_task` via `call_tool`) and **all** resource reads (`read_resource`). Writes are intentionally not cached — adding any write tool to `_CACHEABLE_READ_TOOLS` would silently turn duplicate creates into no-ops. Storage is in-memory (resets on server restart) — disk persistence would let stale `events/today` survive restarts. Cache keys are method+args only (no session identity), which is fine for single-user stdio.
  - **Listing caches are explicitly disabled** (`list_tools_settings`/`list_resources_settings`/`list_prompts_settings` set to `{"enabled": False}`). The middleware caches `tools/list`/`resources/list`/`prompts/list` **by default** with a 5-minute TTL if you pass `None`; but listing is a pure in-memory component enumeration (no API call), so the cache saves nothing and only risks serving a stale set. Critically, read-only mode toggles tool visibility, and a cached `tools/list` would mask that for up to 5 minutes. Do **not** re-enable listing caches.
  - **Test isolation**: because the cache is a module-level singleton on `mcp` keyed on method+args (no session partition), two tests that call the same cacheable read tool with the same args collide across the 60s TTL. Tests either use disjoint keys (`TestResponseCaching`) or evict via the public `keys()`+`delete()` API in an autouse fixture (`TestTypedOutputSchemas::_isolate_cache`). Never call `_backend.destroy()` — it tears down collection-setup state and breaks every subsequent `put` in the process.
- Tools return `{"success": True, ...}` on success
- Tools raise `ToolError` (from `fastmcp.exceptions`) on failure — messages are always visible to LLMs
- `@handle_tool_errors` in `utils.py` converts ValidationError, MorgenAPIError, and unexpected exceptions to ToolError
- Batch operations return partial results with `{"deleted": [...], "failed": [...]}` — per-item failures are dict entries, not ToolError
- **Typed output schemas**: Every tool declares a `TypedDict` return from `tools/outputs.py` (not `models.py` — those are alias-based wire models with a different shape than the hand-built camelCase output dicts like `calendarId`/`isAllDay`). This gives each tool a shaped `outputSchema` **and** makes FastMCP validate every return against it at runtime — a payload missing a schema-`required` field raises `ToolError: Output validation error: '<field>' is a required property`. Because tool payloads run through `filter_none_values` (drops None/empty keys), **any field that can be absent MUST be `NotRequired`**, or a normal sparse response (account with no `displayName`, event with no `description`) fails. Nested "always-present-but-nullable" values (e.g. `update_calendar_metadata`'s `updated.overrideColor`) are typed `T | None` (key required, value nullable), not `NotRequired`. The `_format_*` helpers are typed to return their item TypedDict via `cast(...)` at the `filter_none_values` boundary (resolves list-invariance under pyright). `TestTypedOutputSchemas` locks the `NotRequired` decisions into CI.
- **Read-only launch mode**: `MORGENMCP_READ_ONLY` (truthy env) or `--read-only` (CLI flag, parsed in `main()`) calls `mcp.disable(tags={"write", "delete"})` **once at startup, before `mcp.run()`** (`_apply_read_only` in `server.py`). This hides + disables the 16 mutating tools, leaving the 6 reads. The tag taxonomy is a complete gate (every mutating tool carries `write` or `delete`, verified by tag tests). Applied at startup so the disabled state is in the first `list_tools` — and because listing caches are disabled, `disable`/`enable` are reflected immediately (a default-cached `tools/list` would have masked the toggle for 5 min). Disabled tools are both unlisted and uncallable through the protocol.
- Datetime fields use LocalDateTime format (`2023-03-01T10:00:00`) - no Z suffix; timezone is separate
- `EventCreateResponse` has nested structure: `response.event.id`, not `response.id`
- **Timing fields constraint**: `update_event` and `batch_update_events` require all four timing fields (`start`, `duration`, `time_zone`, `is_all_day`) together or none — partial updates are rejected
- **Alerts**: Tools accept negative ISO 8601 offsets (e.g., `'-PT15M'`) and convert them to Morgen's base64-encoded alert ID format (`base64(JSON({a:'display',to:offset}))`). `alerts` and `use_default_alerts` are mutually exclusive.
- **Recurrence rules**: Accept simplified dicts `{frequency, interval, by_day}`; the `build_recurrence_rules` helper converts to JSCalendar `RecurrenceRule` objects.
- **Tags endpoint quirk**: `/tags/list` returns a bare JSON array, not the standard `{data: ...}` envelope — the client handles both shapes.
- **HTTP client hardening** (`client.py`): `_RetryAfterTransport` retries a request **once** when Morgen answers 429 with a short `Retry-After` (≤10s; longer hints and the HTTP-date form surface the 429 immediately). The transport wraps a real `AsyncHTTPTransport` with `Limits(max_connections=10)` and `retries=1` (connect errors), so respx still intercepts in tests. Timeouts are split (`Timeout(30, connect=10)`). Upstream error bodies are truncated to 300 chars (`_truncate_error_text`) before landing in `MorgenAPIError`/`ToolError` — a 5xx HTML page or data-echoing body must not reach the LLM verbatim.
- **Bounded batch concurrency**: every batch/fan-out `asyncio.gather` goes through `gather_bounded` (`tools/utils.py`, semaphore, `BATCH_CONCURRENCY = 8`, always `return_exceptions=True`). Applies to `batch_delete_events`, `batch_update_events`, `batch_delete_tasks`, the per-account fan-out in `tools/events.py::list_events`, and `resources.py::_fetch_events_in_window` (backing every `morgen://events/*` and `morgen://calendar/{id}/events` resource). Never add a bare `asyncio.gather` over per-item API calls.
- **Startup fail-fast**: `_require_api_key` (`server.py`) rejects a missing/blank `MORGEN_API_KEY` both in `main()` (clean argparse error) and at the top of the lifespan (covers programmatic use). Without it the server would start, advertise all tools, and fail lazily on the first call.
- **No raw Morgen IDs in client-visible text**: warnings/errors surfaced via `ctx.warning` or `ToolError` must reference **virtual** IDs (`register_id(...)`) — raw calendar/event IDs base64-decode to email addresses.
- **EventUpdateRequest.alerts** uses `dict[str, Alert | None]` to support patch-style removal (set entry to `None` to delete that alert). `EventCreateRequest.alerts` uses the same widened type for consistency at type-check time, even though create never accepts None values.
- **Display timezone for compact events**: `_format_compact_event` converts event times into a display tz resolved by `_resolve_display_tz`: explicit `display_timezone` arg on `morgen_list_events` → `MORGENMCP_DISPLAY_TZ` env var → system local timezone. Every compact line includes a `MMM DD` date prefix so multi-day listings remain scannable. Rendered lines look like `"Jul 15 09:15-10:00 CDT (America/Chicago): Standup [abc123]"`. All-day events render as `"Jul 15 (all-day): Holiday [abc123]"`. Floating events (`time_zone=None`) are tagged `(floating)` and not converted. Cross-midnight conversions get a date prefix on the end side as well. Resources have no per-call argument path — they rely on env/system fallback only.

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

- **Storage location**: `~/Library/Application Support/morgenmcp/id_store/` (via `platformdirs.user_data_dir`), `chmod 0o700` after setup — persisted entries hold raw Morgen IDs, which decode to email addresses
- **Override**: Set `MORGENMCP_DATA_DIR` env var to use a custom directory
- **Graceful degradation**: If the store fails to initialize, the server continues with in-memory-only IDs (session-scoped)
- **Tests**: Persistence is disabled by an `autouse` conftest fixture (`set_store(None)`)

**Stability contract**: The hash output is governed by `HASH_SPEC` in `id_registry.py` — algorithm (MD5), input encoding (UTF-8), digest slice (6 bytes), output length (7 chars Base64url, no padding). The contract is published to MCP consumers via the `morgen://server` resource and pinned by `tests/test_id_persistence.py::TestVirtualIdGoldenVectors`. The current scheme version is `HASH_SCHEME_VERSION = 1`.

**What is hashed**: the raw `real_id` string exactly as Morgen returns it. Not a Pydantic model, not a JSON-serialized envelope. UTF-8 encoded. See the `reference_implementation` field in `HASH_SPEC` for the canonical one-line expression — a downstream consumer can reimplement it and verify against the `test_vectors` map.

**When (and only when) it is OK to break the hash**: Bump `HASH_SCHEME_VERSION` in the same commit that changes the output. Never reuse a version. Consumers detect the change by re-reading `morgen://server` between sessions; a bumped `scheme_version` signals that any stored virtual ID is stale and must be re-resolved by calling the relevant `list_*` tool. The persisted store under `~/Library/Application Support/morgenmcp/id_store/` survives the bump (old IDs still resolve from disk), but *new* registrations for the same real ID will diverge — plan a migration (e.g. one-shot store wipe + re-list on startup) in the same PR.

### Environment variables

- **`MORGEN_API_KEY`**: Required. Morgen API key. Checked at startup (`_require_api_key`) — the server refuses to start without it instead of failing lazily on the first tool call.
- **`MORGENMCP_DATA_DIR`**: Override the virtual-ID persistence directory.
- **`MORGENMCP_DISPLAY_TZ`**: IANA timezone (e.g. `America/Chicago`) for rendering compact event times in `morgen_list_events` (when `compact=True`) and all `morgen://events/*` resources. Defaults to the system local timezone. Overridden per-call via the `display_timezone` arg on `morgen_list_events`.
- **`MORGENMCP_READ_ONLY`**: Truthy (`1`/`true`/`yes`/`on`, case-insensitive) launches the server read-only: all mutating tools (everything tagged `write` or `delete` — 16 create/update/delete/complete/reopen/move/batch tools) are disabled, leaving only the 6 read tools. Equivalent to the `--read-only` CLI flag (`uv run morgenmcp --read-only`); either one enables it. Applied once at startup, before `mcp.run()`, so the disabled state is baked into the first `list_tools` response.

### Testing

- **Tool tests** (`test_tools.py`): Mock via `patch("morgenmcp.tools.*.get_client")`
- **Client tests** (`test_client.py`): Mock HTTP via `@respx.mock` decorator on test methods
- **MCP protocol tests** (`test_mcp_server.py`): In-memory protocol-level tests using `fastmcp.Client(mcp)` — verifies tool registration, annotations, and end-to-end call flow. Uses `MORGENMCP_DATA_DIR=tmp_path` to isolate the persistent store.
- **Persistence tests** (`test_id_persistence.py`): Tests FileTreeStore write-through and cross-session restore using real temp-dir-backed stores
- **Integration tests** (`test_integration.py`): Hit real API, excluded from CI via pytest marker

### Environment

- Python `>= 3.14` (set in `pyproject.toml`)
- `fastmcp>=3.4,<3.5` — pinned to 3.4.x patch range

## Versioning & Release

Versions are managed via git tags. No build step required.

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Users reference tags in their MCP client config: `git+https://github.com/k3KAW8Pnf7mkmdSMPHz27/MorgenMCP@v0.1.0`

## Documentation Resources

**IMPORTANT: Always use the local docs submodules as the primary source of truth.** They are version-pinned to match the exact dependency versions in this project. Online docs may describe newer or older API versions that do not match what this project uses. Only fall back to online docs when local docs are insufficient.

**Caveat — the Morgen docs describe intent, not always behavior.** They are the
right starting point and beat online sources, but they are not authoritative
about runtime behavior; at least one documented parameter default does not match
what the live endpoint does. The Morgen submodule is also pinned to a *branch*
commit (`john/use-new-rate-liimit-values-6`), not a release tag, so it may not
match what is deployed. When a doc claim drives a code change, confirm it with a
read-only probe against the live API where that is cheap.

When spawning Explore agents, **always include this instruction in the prompt**: _"For Morgen API questions, search `docs/morgen-dev-docs/content/` first. For FastMCP questions, search `docs/fastmcp/docs/` first. These local docs match the pinned dependency versions and take priority over online sources."_

### Local docs (primary — version-pinned, must be initialized)

| Source | Path | Covers |
|--------|------|--------|
| **Morgen API** | `docs/morgen-dev-docs/content/*.mdx` | Endpoints, parameters, schemas, changelog |
| **FastMCP** | `docs/fastmcp/docs/` | Server framework: tools, context, auth, testing, deployment |

- **Morgen docs submodule**: pinned at `f977d08`
- **FastMCP docs submodule**: pinned at `1eedd1f6` (`v3.4.3`, matching the `fastmcp>=3.4,<3.5` pin); cloned `shallow = true`, so it carries no tags and `git describe` will fail

**These are git submodules and are NOT populated by a fresh clone.** Nothing
updates them automatically — there is no hook that does this. Check and
initialize them before relying on any lookup rule below:

```bash
git submodule status                # a leading '-' means uninitialized/empty
git submodule update --init         # populate both
```

An uninitialized submodule is an empty directory, so a `grep` over
`docs/morgen-dev-docs/content/` silently returns nothing rather than erroring.
Treat "no matches" as "check `git submodule status` first", not as "the docs
don't cover it" — otherwise every rule in this section quietly degrades to
guessing from memory or reaching for the live API.

### Online docs (fallback only)

| Source | URL | When to use |
|--------|-----|-------------|
| **Morgen API** | https://docs.morgen.so/ | Only if local MDX files lack the endpoint or field you need |
| **FastMCP** | https://gofastmcp.com/llms.txt | Only if local docs under `docs/fastmcp/docs/` don't cover the topic |
| **MCP Protocol** | https://modelcontextprotocol.io/llms.txt | Protocol spec: transports, tool schema, JSON-RPC messages (no local copy) |

### Lookup rules

1. **Before implementing or modifying any tool**: Search `docs/morgen-dev-docs/content/*.mdx` directly (grep for the endpoint or resource name, read the matching file) to confirm parameters, required fields, and response shapes. Only cross-reference online docs if the local result is incomplete.
2. **For FastMCP patterns** (tool registration, return types, error handling, testing): Search `docs/fastmcp/docs/` directly — grep for the pattern (decorator, `Context` method, error class, testing helper) and read the matching file for file paths, line numbers, and code examples. These docs match the installed FastMCP version exactly.
3. **For MCP protocol questions** (transport, JSON-RPC, tool schema): Fetch `https://modelcontextprotocol.io/llms.txt` first, then the relevant spec page (no local copy exists).
4. **When adding a new tool or changing tool signatures**: Check both FastMCP local docs (for decorator/return-type patterns) and the MCP protocol spec (for schema requirements) to ensure compliance.
5. **When spawning any agent** (Explore, Plan, or general-purpose) that may need API or framework information: Include the local doc paths in the prompt (`docs/morgen-dev-docs/content/` for Morgen API, `docs/fastmcp/docs/` for FastMCP) so the subagent searches them directly rather than guessing or using online sources.
