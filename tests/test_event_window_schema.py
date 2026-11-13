"""Protocol coverage for event query window bounds."""

from __future__ import annotations

from fastmcp import Client

from morgenmcp.server import mcp


async def test_list_events_schema_documents_suffixless_utc_bounds():
    async with Client(mcp) as client:
        tools = await client.list_tools()

    tool = next(tool for tool in tools if tool.name == "morgen_list_events")
    for bound in ("start", "end"):
        description = tool.inputSchema["properties"][bound]["description"]
        assert "UTC" in description
        assert "without a Z" in description
        assert "numeric offset" in description
