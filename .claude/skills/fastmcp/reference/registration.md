# Tool / resource / prompt registration

Sources: `docs/fastmcp/docs/servers/tools.mdx`, `docs/fastmcp/docs/servers/resources.mdx`.

## Registration forms

Bare decorator:
```python
@mcp.tool
def my_tool(x: int) -> int: ...

@mcp.resource("users://email/{email}")
def lookup_user(email: str) -> dict: ...
```

With options:
```python
@mcp.tool(name=..., description=..., tags={...}, meta={...}, timeout=float, output_schema={...})
```

**Call-expression form** (what MorgenMCP uses in `server.py`, so functions stay plain and
independently testable):
```python
mcp.resource("users://email/{email}")(lookup_user)
mcp.tool(name="morgen_list_events")(list_events)
```
This also lets one function register under multiple URIs/names by calling it more than once.

For bound methods, use `fastmcp.tools.tool()` standalone then `mcp.add_tool(bound_method)` —
the decorator form doesn't work directly on instance/class methods.

## Primitive-result auto-wrapping

MCP structured-output schemas require an object root. FastMCP handles this automatically based
on the function's return annotation:
- Annotated primitive (e.g. `-> int`) → wrapped into `structuredContent: {"result": 8}`, with
  `"x-fastmcp-wrap-result": true` on the schema. Clients auto-unwrap this into `.data`.
- No return annotation → no `structuredContent` at all, only `content`.
- `dict` / dataclass / Pydantic model → always becomes structured content directly, no wrapping,
  even without an explicit `output_schema`.
- Full manual control: return `ToolResult(content=..., structured_content=..., meta=...)` —
  importable as `from fastmcp.tools import ToolResult` (or `fastmcp.tools.tool`, a runtime
  `sys.modules` alias; the actual class lives in `fastmcp/tools/base.py`, not a `tool.py` file).

MorgenMCP's tools return `{"success": True, ...}` dicts (per `CLAUDE.md`), so they land in the
"dict → structured content directly" case — no wrapping envelope to worry about.

## Error handling

- `ToolError` (`fastmcp.exceptions`) messages are **always** sent to the client verbatim,
  regardless of the `mask_error_details` setting on `FastMCP(...)`.
- Generic exceptions (`TypeError`, `ValueError`, etc.) get masked to a generic string when
  `mask_error_details=True`.
- No `fastmcp.ValidationError` is documented for tool/resource handlers in these files —
  argument validation failures come from Pydantic coercion. Coercion strictness is controlled by
  `strict_input_validation` (default: flexible coercion; `FastMCP(strict_input_validation=True)`
  enforces strict JSON-Schema validation instead).
- This is why `morgenmcp/tools/utils.py`'s `@handle_tool_errors` converts `ValidationError`,
  `MorgenAPIError`, and unexpected exceptions to `ToolError` — it's the only exception type
  guaranteed to reach the client with a useful message.

## RFC 6570 URI templates (resources)

`docs/fastmcp/docs/servers/resources.mdx` §"RFC 6570 URI Templates":
- `{param}` — exactly one path segment, does not cross `/`.
- `{param*}` — wildcard, captures multiple segments up to the next literal/param:
  `@mcp.resource("path://{filepath*}")`.
- `{?param1,param2}` — form-style query params (v2.13.0+). Must map to *optional* (defaulted)
  function params; path params must map to *required* params:
  ```python
  @mcp.resource("data://{id}{?format}")
  def get_data(id: str, format: str = "json"): ...
  ```
  Values are auto-coerced to `int`/`float`/`bool`/`str` per type hint.

## Return type: `ResourceResult`

Introduced v3.0.0. `ResourceResult(contents=str|bytes|list[ResourceContent], meta=dict|None)`;
`ResourceContent(content=Any, mime_type=str|None, meta=dict|None)`. Plain `str` becomes
`TextResourceContents`, `bytes` becomes `BlobResourceContents` (base64-encoded). Simple resources
can just return `str`/`bytes` directly without constructing `ResourceResult`.
