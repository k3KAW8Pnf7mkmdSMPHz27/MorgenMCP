"""Protocol coverage for event query window bounds."""

from __future__ import annotations

from fastmcp import Client

from morgenmcp.server import mcp


async def test_list_events_schema_documents_timezone_window_bounds():
    async with Client(mcp) as client:
        tools = await client.list_tools()

    tool = next(tool for tool in tools if tool.name == "morgen_list_events")
    props = tool.inputSchema["properties"]
    for bound in ("start", "end"):
        description = props[bound]["description"]
        assert "UTC" in description
        assert "YYYY-MM-DDTHH:mm:ss" in description
        assert "time_zone" in description
    assert "time_zone" in props
    assert "IANA" in props["time_zone"]["description"]
