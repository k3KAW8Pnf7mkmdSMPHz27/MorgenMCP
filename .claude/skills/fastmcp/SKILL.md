---
name: fastmcp
description: Up-to-date reference for FastMCP (Python MCP server framework) as used in MorgenMCP — middleware authoring, tool/resource/prompt registration, ToolError conventions, in-memory Client testing, transports. Use when modifying morgenmcp/server.py, tools/, resources.py, or writing/debugging tests against fastmcp.Client. Prefer this over memory: verify against docs/fastmcp/docs/ (pinned submodule) before relying on any API detail — FastMCP ships breaking changes across 3.x minors.
user-invocable: true
---

# FastMCP reference (MorgenMCP)

**Pinned version: 3.4.3** (`pyproject.toml`: `fastmcp>=3.4,<3.5`). Local docs submodule
`docs/fastmcp/` is checked out at tag `v3.4.3` (`1eedd1f6`) — matches the installed package
exactly. **Always check `docs/fastmcp/docs/` before trusting a remembered API detail** —
online docs and this skill's own prose can describe a different version.

> Facts here were verified against the pinned submodule and cross-checked with a deep-research
> pass (2026-07-07). Re-verify before relying on a signature if the submodule tag has moved —
> see reference/CHANGELOG.md.

## Where MorgenMCP deviates from FastMCP defaults (know these first)

- **Call-expression registration, not decorators.** `server.py` uses `mcp.tool(name=...)(func)` /
  `mcp.resource(uri, ...)(func)` instead of `@mcp.tool`. This is a documented-valid alternative
  (see reference/registration.md) chosen so tool/resource functions stay plain, independently
  importable async functions for unit testing.
- **`ResponseCachingMiddleware` is a FastMCP-provided class**, imported directly from
  `fastmcp.server.middleware.caching` (not subclassed). MorgenMCP's contribution is only the
  *configuration* — `CallToolSettings`/`ReadResourceSettings` (60s TTL, which tools/resources are
  cached) — so a FastMCP upgrade touching this module directly affects this repo's cache behavior.
- **stdio transport only**, no HTTP/auth surface. FastMCP auth (OAuth Proxy, MultiAuth) is
  HTTP-only by design — under stdio it is silently skipped, not rejected (`run_stdio_async` never
  reads `self.auth`; the server runs with `skip_auth=True`). So auth is simply inert here, and
  auth-hardening changelog entries can be skipped when assessing upgrade risk for this repo.

## Quick recipes

**Middleware** (subclass `fastmcp.server.middleware.Middleware`, register via `mcp.add_middleware`):
```python
from fastmcp.server.middleware import Middleware, MiddlewareContext

class LoggingMiddleware(Middleware):
    async def on_message(self, context: MiddlewareContext, call_next):
        return await call_next(context)

mcp.add_middleware(LoggingMiddleware())  # order = execution order, first added = outermost
```
Deny by **raising**, not returning falsy: `ToolError` / `ResourceError` / `PromptError` / `McpError`.
`on_initialize` must reject *before* calling `call_next()` — raising after only logs.

**Registration** (call-expression form, as used in this repo):
```python
mcp.tool(name="morgen_list_events", description=...)(list_events)
mcp.resource("morgen://calendar/{calendar_id}/events")(get_calendar_events)
```

**Testing** (in-memory, no transport — pass the server instance directly):
```python
from fastmcp import Client

async def test_x():
    async with Client(mcp) as client:
        result = await client.call_tool("morgen_list_events", {...})
        assert result.data == {...}
```
Don't open `Client` inside a pytest fixture (event-loop issues) — only build/return the server there.

**Errors**: `ToolError` messages are *always* sent to the client, regardless of `mask_error_details`.
Generic exceptions get masked to a generic string when `mask_error_details=True`. This is why
`utils.py`'s `@handle_tool_errors` converts everything to `ToolError`.

**Transport** (this repo only uses the first):
```python
mcp.run()                                              # stdio (default) — what MorgenMCP uses
mcp.run(transport="http", host="127.0.0.1", port=8000) # Streamable HTTP → http://host:port/mcp
```

## Topic reference (load as needed)

- Middleware hook signatures, `MiddlewareContext` fields, deny-by-raising details → [reference/middleware.md](reference/middleware.md)
- Tool/resource/prompt registration forms, primitive-result auto-wrapping, RFC 6570 URI templates → [reference/registration.md](reference/registration.md)
- Testing patterns (in-memory Client, `run_server_async` vs `run_server_in_process`) → [reference/testing.md](reference/testing.md)
- Per-version changelog (3.0.0 → 3.4.3), what's a breaking change, security-hardening timeline → [reference/CHANGELOG.md](reference/CHANGELOG.md)

## Why FastMCP here (context)

MorgenMCP wraps the Morgen calendar API as an MCP server. It runs stdio-only with no auth
provider, registers 22 tools, and layers FastMCP's `ResponseCachingMiddleware` (60s TTL,
configured not subclassed) plus a virtual-ID system on top of FastMCP's tool/resource primitives.
See the project's own `CLAUDE.md` for the full architecture — this skill only covers the FastMCP
framework layer.
