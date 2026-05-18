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
def _use_tmp_data_dir(tmp_path, monkeypatch):
    """Point persistent store at a temp directory during MCP protocol tests."""
    monkeypatch.setenv("MORGENMCP_DATA_DIR", str(tmp_path))
    clear_registry()
    yield
    clear_registry()


class TestMCPServer:
    """Tests verifying tools through the MCP protocol layer."""

    async def test_all_tools_registered(self):
        """All tools appear with correct names."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools}
            expected = {
                # Accounts
                "morgen_list_accounts",
                # Calendars
                "morgen_list_calendars",
                "morgen_update_calendar_metadata",
                # Events
                "morgen_list_events",
                "morgen_create_event",
                "morgen_update_event",
                "morgen_delete_event",
                "morgen_batch_delete_events",
                "morgen_batch_update_events",
                # Tasks
                "morgen_list_tasks",
                "morgen_get_task",
                "morgen_create_task",
                "morgen_update_task",
                "morgen_move_task",
                "morgen_complete_task",
                "morgen_reopen_task",
                "morgen_delete_task",
                "morgen_batch_delete_tasks",
                # Tags
                "morgen_list_tags",
                "morgen_create_tag",
                "morgen_update_tag",
                "morgen_delete_tag",
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
                "morgen_list_tasks",
                "morgen_get_task",
                "morgen_list_tags",
            ]:
                assert by_name[name].annotations.readOnlyHint is True

    async def test_delete_tools_have_destructive_annotation(self):
        """Delete tools are annotated destructiveHint=True."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            by_name = {t.name: t for t in tools}
            for name in [
                "morgen_delete_event",
                "morgen_batch_delete_events",
                "morgen_delete_task",
                "morgen_batch_delete_tasks",
                "morgen_delete_tag",
            ]:
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
                "morgen_create_task",
                "morgen_update_task",
                "morgen_complete_task",
                "morgen_reopen_task",
                "morgen_move_task",
                "morgen_create_tag",
                "morgen_update_tag",
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

    async def test_initialize_advertises_morgenmcp_version(self):
        """serverInfo on initialize carries morgenmcp's __version__, not FastMCP's."""
        from morgenmcp import __version__

        async with Client(mcp) as client:
            assert client.initialize_result is not None
            assert client.initialize_result.serverInfo.name == "morgen-calendar"
            assert client.initialize_result.serverInfo.version == __version__

    async def test_server_resource_published(self):
        """morgen://server is registered and exposes the hash contract."""
        from morgenmcp.tools.id_registry import HASH_SCHEME_VERSION

        async with Client(mcp) as client:
            resources = await client.list_resources()
            uris = {str(r.uri) for r in resources}
            assert "morgen://server" in uris

            payload = await client.read_resource("morgen://server")
            body = json.loads(payload[0].text)
            assert body["name"] == "morgen-calendar"
            assert body["virtualIdHash"]["scheme_version"] == HASH_SCHEME_VERSION
            assert body["virtualIdHash"]["algorithm"] == "md5"

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

    async def test_all_resources_registered(self):
        """All resources and resource templates appear with the morgen:// scheme."""
        async with Client(mcp) as client:
            resources = await client.list_resources()
            templates = await client.list_resource_templates()

            static_uris = {str(r.uri) for r in resources}
            template_uris = {t.uriTemplate for t in templates}

            assert static_uris == {
                "morgen://server",
                "morgen://accounts",
                "morgen://calendars",
                "morgen://events/today",
                "morgen://events/this-week",
                "morgen://events/upcoming",
                "morgen://tasks",
                "morgen://tasks/today",
                "morgen://tags",
            }
            assert template_uris == {
                "morgen://account/{account_id}",
                "morgen://calendar/{calendar_id}",
                "morgen://calendar/{calendar_id}/events",
            }

    async def test_read_resource_through_protocol(self):
        """A resource can be read through the full MCP protocol stack."""
        with patch("morgenmcp.resources.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.list_accounts.return_value = []
            mock.return_value = client_mock

            async with Client(mcp) as client:
                contents = await client.read_resource("morgen://accounts")
                assert len(contents) == 1
                payload = json.loads(contents[0].text)
                assert payload == {"accounts": [], "count": 0}


class TestResponseCaching:
    """Tests for ResponseCachingMiddleware behavior — both that read-only
    tools/resources are cached and that writes are NOT (the dangerous case).

    Each test uses disjoint cache keys (distinct tool names / resource URIs /
    arguments) so the shared in-memory cache doesn't cause cross-test leakage.
    Don't add a setup/teardown that calls `_backend.destroy()` — that wipes
    the collection-setup state, breaking subsequent puts in the same session.
    """

    async def test_caching_middleware_is_registered(self):
        """The cache middleware is attached and configured for read-only tools."""
        from fastmcp.server.middleware.caching import ResponseCachingMiddleware

        cache_mws = [
            m for m in mcp.middleware if isinstance(m, ResponseCachingMiddleware)
        ]
        assert len(cache_mws) == 1
        cache_mw = cache_mws[0]
        # Reads only — every other tool (writes, deletes, batch ops) bypasses
        included = cache_mw._call_tool_settings.get("included_tools", [])
        assert "morgen_list_accounts" in included
        assert "morgen_list_calendars" in included
        assert "morgen_list_events" in included
        assert "morgen_list_tasks" in included
        assert "morgen_list_tags" in included
        assert "morgen_get_task" in included
        # Writes must NOT be in the allowlist
        for write_tool in (
            "morgen_create_event",
            "morgen_update_event",
            "morgen_delete_event",
            "morgen_batch_delete_events",
            "morgen_batch_update_events",
            "morgen_create_task",
            "morgen_update_task",
            "morgen_delete_task",
            "morgen_complete_task",
            "morgen_reopen_task",
            "morgen_move_task",
            "morgen_create_tag",
            "morgen_update_tag",
            "morgen_delete_tag",
            "morgen_update_calendar_metadata",
        ):
            assert write_tool not in included, f"{write_tool} must not be cached"

    async def test_read_tool_is_cached(self):
        """Two identical calls to a read tool hit the underlying client once."""
        with patch("morgenmcp.tools.calendars.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.list_calendars.return_value = []
            mock.return_value = client_mock

            async with Client(mcp) as client:
                await client.call_tool("morgen_list_calendars", {})
                await client.call_tool("morgen_list_calendars", {})

            assert client_mock.list_calendars.await_count == 1

    async def test_write_tool_is_not_cached(self):
        """Two identical calls to a write tool MUST hit the underlying client twice.

        If a write were cached, duplicate creates would silently no-op.
        """
        from morgenmcp.models import CreatedEventInfo, EventCreateResponse

        with patch("morgenmcp.tools.events.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.create_event.return_value = EventCreateResponse(
                event=CreatedEventInfo(
                    id="evt-id",
                    calendar_id="cal-id",
                    account_id="acc-id",
                )
            )
            # Pre-register the calendar virtual ID so the create call resolves
            from morgenmcp.tools.id_registry import register_id

            real_cal_id = (
                base64.b64encode(
                    json.dumps(
                        ["a" * 24, "user@example.com"], separators=(",", ":")
                    ).encode()
                )
                .decode()
                .rstrip("=")
            )
            virtual_cal_id = register_id(real_cal_id)
            mock.return_value = client_mock

            args = {
                "calendar_id": virtual_cal_id,
                "title": "Same title",
                "start": "2026-06-01T10:00:00",
                "duration": "PT1H",
                "time_zone": "America/Chicago",
            }

            async with Client(mcp) as client:
                await client.call_tool("morgen_create_event", args)
                await client.call_tool("morgen_create_event", args)

            assert client_mock.create_event.await_count == 2

    async def test_resource_read_is_cached(self):
        """Two reads of the same resource URI hit the underlying client once."""
        with patch("morgenmcp.resources.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.list_tags.return_value = []
            mock.return_value = client_mock

            async with Client(mcp) as client:
                await client.read_resource("morgen://tags")
                await client.read_resource("morgen://tags")

            assert client_mock.list_tags.await_count == 1

    async def test_different_args_bypass_cache(self):
        """Different arguments produce different cache keys (no false hits)."""
        from morgenmcp.tools.id_registry import register_id

        # Pre-register a calendar so we can target it directly and avoid the
        # list_calendars fan-out (which would empty-shortcut on a [] mock).
        real_cal_id = (
            base64.b64encode(
                json.dumps(
                    ["c" * 24, "cache@example.com"], separators=(",", ":")
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        virtual_cal_id = register_id(real_cal_id)

        with patch("morgenmcp.tools.events.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.list_events.return_value = []
            mock.return_value = client_mock

            async with Client(mcp) as client:
                await client.call_tool(
                    "morgen_list_events",
                    {
                        "start": "2026-06-01T00:00:00",
                        "end": "2026-06-02T00:00:00",
                        "calendar_ids": [virtual_cal_id],
                    },
                )
                await client.call_tool(
                    "morgen_list_events",
                    {
                        "start": "2026-06-02T00:00:00",
                        "end": "2026-06-03T00:00:00",
                        "calendar_ids": [virtual_cal_id],
                    },
                )

            # Different windows ⇒ two underlying fetches
            assert client_mock.list_events.await_count == 2
