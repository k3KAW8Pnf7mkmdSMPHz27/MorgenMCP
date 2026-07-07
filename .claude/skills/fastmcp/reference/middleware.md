# Middleware

Source: `docs/fastmcp/docs/servers/middleware.mdx` (pinned v3.4.3).

## Authoring

Subclass `fastmcp.server.middleware.Middleware`, override the hooks you need:

```python
from fastmcp.server.middleware import Middleware, MiddlewareContext

class LoggingMiddleware(Middleware):
    async def on_message(self, context: MiddlewareContext, call_next):
        result = await call_next(context)
        return result
```

Register on a server instance:

```python
mcp.add_middleware(LoggingMiddleware())
```

`add_middleware` (`fastmcp_slim/fastmcp/server/server.py:527`):
```python
def add_middleware(self, middleware: Middleware) -> None:
    self.middleware.append(middleware)
```
Registration order = execution order for the request leg; **reversed** for the response leg
(first-added middleware is outermost — sees the request first, the response last). This repo's
`ResponseCachingMiddleware` registration order in `server.py` therefore determines whether other
middleware sees pre- or post-cache traffic.

## Hook signatures

All hooks share the same shape:
```python
async def hook(self, context: MiddlewareContext, call_next) -> result_type
```

Most general → most specific:
- `on_message` — every message, requests + notifications
- `on_request` / `on_notification`
- `on_call_tool`, `on_read_resource`, `on_get_prompt`
- `on_list_tools`, `on_list_resources`, `on_list_resource_templates`, `on_list_prompts`
- `on_initialize`

Override `__call__` directly instead of the named hooks for raw/uniform handling of every message
type without dispatch overhead.

`MiddlewareContext` fields: `method`, `source`, `type`, `message`, `timestamp`, `fastmcp_context`.
- Tool/prompt calls: `context.message.name`, `context.message.arguments`
- Resource reads: `context.message.uri`

`on_list_tools` returns `list[Tool]` — filter/mutate the list before returning to hide tools from
specific clients.

## Denying requests

Raise, don't return falsy:
- `ToolError` — tool calls
- `ResourceError` — resource reads
- `PromptError` — prompt gets
- `McpError` — general/protocol-level

**`on_initialize` must reject *before* calling `call_next()`.** Raising after `call_next()`
returns only logs the error server-side — it does not reach the client, because the initialize
response has already been dispatched.

## Caching middleware — is a framework feature

FastMCP ships a built-in response-caching middleware:
`fastmcp.server.middleware.caching.ResponseCachingMiddleware`, confirmed directly against the
installed package (`.venv/lib/python3.14/site-packages/fastmcp/server/middleware/caching.py`,
593 lines). It comes with per-method settings classes — `CallToolSettings`,
`ReadResourceSettings`, `ListToolsSettings`, `ListResourcesSettings`, `ListPromptsSettings`,
`GetPromptSettings` (all `TypedDict`s controlling TTL/enable per operation) — plus
`ResponseCachingStatistics` and cache-key partitioning by auth token.

`morgenmcp/server.py` imports and configures this class directly (not a subclass): 60s TTL,
an explicit allowlist of cacheable read-only tools plus all resources. Upgrading FastMCP *can*
change this repo's caching behavior if a release touches `fastmcp.server.middleware.caching` —
check that module's diff specifically, not just the general `Middleware` base class, when
assessing upgrade risk (see reference/CHANGELOG.md for the version-by-version history and a
past false-negative on this exact claim).
