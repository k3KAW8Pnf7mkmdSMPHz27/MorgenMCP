# Testing patterns

Source: `docs/fastmcp/docs/development/tests.mdx`.

## In-memory Client testing (the pattern to use)

Pass the `FastMCP` server instance directly to `Client` — this runs the real MCP protocol in the
same process, no network transport, no subprocess:

```python
from fastmcp import FastMCP, Client

server = FastMCP("WeatherServer")

@server.tool
def get_temperature(city: str) -> dict:
    return {"city": city, "temp": temps.get(city, 70)}

async def test_weather_operations():
    async with Client(server) as client:
        result = await client.call_tool("get_temperature", {"city": "NYC"})
        assert result.data == {"city": "NYC", "temp": 72}
```

**Don't open `Client` inside a pytest fixture** — event-loop lifecycle issues. Only build/return
the server instance from fixtures; open the `Client` context manager inside the test function
itself.

This is exactly the pattern MorgenMCP's `test_mcp_server.py` uses: `fastmcp.Client(mcp)` against
the real server object, with `MORGENMCP_DATA_DIR=tmp_path` to isolate the persistent ID store.

## Real network transport (rarely needed)

Two options, in order of preference:
- `fastmcp.utilities.tests.run_server_async(server) as url` — in-process, async context manager.
  Prefer this when you actually need a URL (e.g. testing HTTP-specific behavior).
- `run_server_in_process` — spawns a real subprocess. Only use when true process isolation is
  required (e.g. testing stdio transport specifically, or crash isolation).

MorgenMCP doesn't currently need either — all tests go through the in-memory `Client` pattern or
mock the HTTP client directly (`test_client.py` via `@respx.mock`, `test_tools.py` via
`patch("morgenmcp.tools.*.get_client")`).
