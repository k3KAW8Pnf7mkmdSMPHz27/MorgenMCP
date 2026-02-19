"""MCP protocol-level tests using FastMCP in-memory Client."""

import base64
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client
from fastmcp.client.logging import LogMessage

from morgenmcp.models import Calendar, MorgenAPIError
from morgenmcp.server import mcp
from morgenmcp.tools.id_registry import clear_registry


@pytest.fixture(autouse=True)
def clear_ids():
    clear_registry()
    yield
    clear_registry()


class TestMCPServer:
    """Tests verifying tools through the MCP protocol layer."""

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

    async def test_delete_tools_have_destructive_annotation(self):
        """Delete tools are annotated destructiveHint=True."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            by_name = {t.name: t for t in tools}
            for name in ["morgen_delete_event", "morgen_batch_delete_events"]:
                assert by_name[name].annotations.destructiveHint is True

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

    async def test_all_tools_have_title(self):
        """All tools have a non-empty title annotation."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            for tool in tools:
                assert tool.annotations is not None, f"{tool.name} missing annotations"
                assert tool.annotations.title, f"{tool.name} missing title annotation"

    async def test_call_tool_through_protocol(self):
        """A tool can be called through the full MCP protocol stack."""
        with patch("morgenmcp.tools.accounts.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.list_accounts.return_value = []
            mock.return_value = client_mock

            async with Client(mcp) as client:
                result = await client.call_tool("morgen_list_accounts", {})
                assert result is not None

    async def test_list_events_partial_failure_returns_results(self):
        """list_events returns events from healthy accounts when one account fails.

        Uses FastMCP 3.0 log_handler/progress_handler to verify warnings and
        progress are sent through the MCP protocol (not just in the return value).
        """
        account_id_1 = "aaaa00000000000000000001"
        account_id_2 = "aaaa00000000000000000002"

        def _cal_id(acc_id: str, email: str) -> str:
            return (
                base64.b64encode(
                    json.dumps([acc_id, email], separators=(",", ":")).encode()
                )
                .decode()
                .rstrip("=")
            )

        def _evt_id(email: str, uid: str, acc_id: str) -> str:
            return (
                base64.b64encode(
                    json.dumps([email, uid, acc_id], separators=(",", ":")).encode()
                )
                .decode()
                .rstrip("=")
            )

        cal1 = Calendar(
            id=_cal_id(account_id_1, "a@test.com"),
            account_id=account_id_1,
            integration_id="google",
        )
        cal2 = Calendar(
            id=_cal_id(account_id_2, "b@test.com"),
            account_id=account_id_2,
            integration_id="o365",
        )

        from morgenmcp.models import Event

        evt = Event(
            id=_evt_id("a@test.com", "uid1", account_id_1),
            calendar_id=cal1.id,
            account_id=account_id_1,
            integration_id="google",
            title="Survived",
            start="2025-01-01T10:00:00",
            duration="PT1H",
        )

        collected_logs: list[LogMessage] = []
        progress_updates: list[tuple[float, float | None]] = []

        async def log_handler(message: LogMessage) -> None:
            collected_logs.append(message)

        async def progress_handler(
            progress: float, total: float | None, message: str | None
        ) -> None:
            progress_updates.append((progress, total))

        with patch("morgenmcp.tools.events.get_client") as mock:
            client_mock = AsyncMock()
            mock.return_value = client_mock
            client_mock.list_calendars.return_value = [cal1, cal2]

            # First account returns events, second raises
            async def _list_events(**kwargs):
                if kwargs["account_id"] == account_id_1:
                    return [evt]
                raise MorgenAPIError("timeout", status_code=504)

            client_mock.list_events.side_effect = _list_events

            async with Client(
                mcp, log_handler=log_handler, progress_handler=progress_handler
            ) as client:
                result = await client.call_tool(
                    "morgen_list_events",
                    {"start": "2025-01-01T00:00:00", "end": "2025-01-02T00:00:00"},
                )

        # Tool should return the surviving events (as JSON text content)
        assert result is not None
        text = result.content[0].text
        assert "Survived" in text

        # Verify warning was sent through the MCP protocol
        assert any(m.level == "warning" for m in collected_logs)

        # Verify progress was reported through the MCP protocol
        assert len(progress_updates) > 0

    async def test_lifespan_closes_client(self):
        """Server lifespan cleans up the HTTP client on shutdown."""
        with patch("morgenmcp.client.get_client") as mock_get:
            client_mock = AsyncMock()
            mock_get.return_value = client_mock

            from morgenmcp.server import lifespan

            async with lifespan(mcp):
                pass

            client_mock.close.assert_awaited_once()
