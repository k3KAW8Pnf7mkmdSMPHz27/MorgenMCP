"""MCP protocol-level tests using FastMCP in-memory Client."""

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client

from morgenmcp.server import mcp
from morgenmcp.tools.id_registry import clear_registry


@pytest.fixture(autouse=True)
def clear_ids():
    clear_registry()
    yield
    clear_registry()


class TestMCPServer:
    """Tests verifying tools through the MCP protocol layer."""

    @pytest.mark.asyncio
    async def test_all_tools_registered(self):
        """All 9 tools appear with correct names."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools}
            expected = {
                "morgen_list_accounts",
                "morgen_list_calendars",
                "morgen_update_calendar_metadata",
                "morgen_list_events",
                "morgen_create_event",
                "morgen_update_event",
                "morgen_delete_event",
                "morgen_batch_delete_events",
                "morgen_batch_update_events",
            }
            assert names == expected

    @pytest.mark.asyncio
    async def test_read_tools_have_readonly_annotation(self):
        """Read tools are annotated readOnlyHint=True."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            by_name = {t.name: t for t in tools}
            for name in [
                "morgen_list_accounts",
                "morgen_list_calendars",
                "morgen_list_events",
            ]:
                assert by_name[name].annotations.readOnlyHint is True

    @pytest.mark.asyncio
    async def test_delete_tools_have_destructive_annotation(self):
        """Delete tools are annotated destructiveHint=True."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            by_name = {t.name: t for t in tools}
            for name in ["morgen_delete_event", "morgen_batch_delete_events"]:
                assert by_name[name].annotations.destructiveHint is True

    @pytest.mark.asyncio
    async def test_write_tools_not_readonly(self):
        """Write tools are annotated readOnlyHint=False."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            by_name = {t.name: t for t in tools}
            for name in [
                "morgen_create_event",
                "morgen_update_event",
                "morgen_update_calendar_metadata",
                "morgen_batch_update_events",
            ]:
                assert by_name[name].annotations.readOnlyHint is False

    @pytest.mark.asyncio
    async def test_call_tool_through_protocol(self):
        """A tool can be called through the full MCP protocol stack."""
        with patch("morgenmcp.tools.accounts.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.list_accounts.return_value = []
            mock.return_value = client_mock

            async with Client(mcp) as client:
                result = await client.call_tool("morgen_list_accounts", {})
                assert result is not None
