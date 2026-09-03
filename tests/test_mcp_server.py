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
                "morgen_list_task_lists",
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
                "morgen_list_task_lists",
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


class TestTypedOutputSchemas:
    """The typed TypedDict returns give each tool a shaped outputSchema, and
    FastMCP validates every return against it at runtime.

    These tests lock in the ``NotRequired`` decisions in ``tools/outputs.py``:
    fields that ``filter_none_values`` can drop MUST stay optional, or a normal
    sparse response would raise ``Output validation error`` in production. A
    future change that over-tightens a field to *required* fails here instead.
    """

    @pytest.fixture(autouse=True)
    async def _isolate_cache(self):
        """Evict the shared response cache before each test in this class.

        ``morgen_list_accounts`` takes no arguments, so its cache key (method +
        args) is identical to the ``morgen_list_accounts`` call in
        ``TestMCPServer`` — which mocks an *empty* account list. Without eviction
        the sparse-account test below would be served that stale ``count: 0``
        payload within the 60s TTL.

        Uses the public ``keys()`` + ``delete()`` API, NOT ``_backend.destroy()``:
        ``destroy`` tears down the collection-setup state and breaks every
        subsequent ``put`` in the process (see ``TestResponseCaching``'s note).
        """
        from fastmcp.server.middleware.caching import ResponseCachingMiddleware

        cache_mw = next(
            m for m in mcp.middleware if isinstance(m, ResponseCachingMiddleware)
        )
        backend = cache_mw._backend
        for collection in ("tools/call", "resources/read"):
            for key in await backend.keys(collection=collection):
                await backend.delete(collection=collection, key=key)
        yield

    async def test_list_accounts_output_schema_is_shaped(self):
        """The tool advertises a real object schema, not the permissive default."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            by_name = {t.name: t for t in tools}
            schema = by_name["morgen_list_accounts"].outputSchema
            assert schema is not None
            assert set(schema.get("properties", {})) >= {"accounts", "count"}
            # A shaped schema constrains keys; the permissive fallback would be
            # {"type": "object", "additionalProperties": true} with no properties.
            assert schema.get("properties")

    async def test_sparse_account_passes_output_validation(self):
        """An account missing displayName (filtered out) still validates.

        ``displayName`` is ``NotRequired`` in ``AccountItem`` precisely because
        ``filter_none_values`` drops it when the provider returns no display
        name. If it were required, this normal payload would error.
        """
        from types import SimpleNamespace

        account = SimpleNamespace(
            id="507f1f77bcf86cd799439011",
            integration_id="o365",
            provider_user_id="user@example.com",
            provider_user_display_name=None,  # -> "displayName" filtered out
        )
        with patch("morgenmcp.tools.accounts.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.list_accounts.return_value = [account]
            mock.return_value = client_mock

            async with Client(mcp) as client:
                result = await client.call_tool("morgen_list_accounts", {})

        assert result.is_error is False
        payload = result.structured_content
        assert payload["count"] == 1
        item = payload["accounts"][0]
        assert item["email"] == "user@example.com"
        assert "displayName" not in item  # filtered, and validation allowed it

    async def test_busy_only_calendar_metadata_update_validates(self):
        """A busy-only metadata update leaves overrideColor/overrideName null.

        ``UpdatedCalendarMetadata`` types those values as ``str | None`` (keys
        always present, values nullable). If they were non-nullable, this
        common partial update would fail output validation.
        """
        real_cal_id = (
            base64.b64encode(
                json.dumps(
                    ["d" * 24, "meta@example.com"], separators=(",", ":")
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        from morgenmcp.tools.id_registry import register_id

        virtual_cal_id = register_id(real_cal_id)

        with patch("morgenmcp.tools.calendars.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.update_calendar_metadata.return_value = None
            mock.return_value = client_mock

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "morgen_update_calendar_metadata",
                    {"calendar_id": virtual_cal_id, "busy": False},
                )

        assert result.is_error is False
        updated = result.structured_content["updated"]
        assert updated["busy"] is False
        assert updated["overrideColor"] is None
        assert updated["overrideName"] is None


class TestReadOnlyMode:
    """Read-only launch mode disables every mutating (write/delete) tool.

    ``_apply_read_only`` mutates the shared module-level ``mcp`` in place, so
    each test restores the full tool set with ``mcp.enable(tags=...)`` in a
    ``finally`` to avoid leaking the disabled state into other tests.
    """

    _READ_TOOLS = {
        "morgen_list_accounts",
        "morgen_list_calendars",
        "morgen_list_events",
        "morgen_list_task_lists",
        "morgen_list_tasks",
        "morgen_get_task",
        "morgen_list_tags",
    }

    def test_read_only_requested_env_parsing(self, monkeypatch):
        """The env-var gate accepts truthy spellings and the CLI flag."""
        from morgenmcp.server import _read_only_requested

        monkeypatch.delenv("MORGENMCP_READ_ONLY", raising=False)
        assert _read_only_requested() is False
        assert _read_only_requested(cli_read_only=True) is True

        for truthy in ("1", "true", "TRUE", "Yes", "on"):
            monkeypatch.setenv("MORGENMCP_READ_ONLY", truthy)
            assert _read_only_requested() is True

        for falsy in ("0", "false", "no", "", "off"):
            monkeypatch.setenv("MORGENMCP_READ_ONLY", falsy)
            assert _read_only_requested() is False

    async def test_default_lists_all_tools(self):
        """Without read-only mode, all 23 tools are visible."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools) == 23

    async def test_read_only_hides_mutating_tools(self):
        """After _apply_read_only, only the 7 read tools are visible, and each
        mutating tool is both unlisted and uncallable.

        Also guards the cache fix: ``ResponseCachingMiddleware`` caches
        ``tools/list`` for 5 min by default, which would mask the visibility
        toggle. The middleware config disables that cache, so the toggle (and
        the ``enable`` restore below) is reflected immediately through the
        client/protocol path.
        """
        from fastmcp.exceptions import ToolError

        from morgenmcp.server import _MUTATING_TAGS, _apply_read_only

        try:
            _apply_read_only(mcp)
            async with Client(mcp) as client:
                names = {t.name for t in await client.list_tools()}
                assert names == self._READ_TOOLS
                # A disabled tool is not merely unlisted — calling it fails.
                with pytest.raises(ToolError):
                    await client.call_tool("morgen_create_event", {})
        finally:
            mcp.enable(tags=_MUTATING_TAGS)

        # enable() restore is visible immediately (list_tools is not cached).
        async with Client(mcp) as client:
            assert len({t.name for t in await client.list_tools()}) == 23


class TestRequireApiKey:
    """Startup fails fast when MORGEN_API_KEY is missing.

    ``_require_api_key`` runs both in ``main()`` (clean argparse error) and at
    the top of the lifespan (covers programmatic/embedded use), so a
    misconfigured server never starts, advertises tools, and then fails
    lazily on the first call.
    """

    def test_missing_key_raises(self, monkeypatch):
        from morgenmcp.server import _require_api_key

        monkeypatch.delenv("MORGEN_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="MORGEN_API_KEY is not set"):
            _require_api_key()

    def test_blank_key_raises(self, monkeypatch):
        from morgenmcp.server import _require_api_key

        monkeypatch.setenv("MORGEN_API_KEY", "   ")
        with pytest.raises(RuntimeError, match="MORGEN_API_KEY is not set"):
            _require_api_key()

    def test_present_key_passes(self, monkeypatch):
        from morgenmcp.server import _require_api_key

        monkeypatch.setenv("MORGEN_API_KEY", "some-key")
        _require_api_key()  # must not raise


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
        assert "morgen_list_task_lists" in included
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


class TestLimitConfig:
    """CLI/env wiring for the per-endpoint list limits (_apply_limit_config)."""

    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch):
        from morgenmcp.client import (
            TAGS_LIMIT_ENV,
            TASKS_LIMIT_ENV,
            set_limit_override,
        )

        monkeypatch.delenv(TASKS_LIMIT_ENV, raising=False)
        monkeypatch.delenv(TAGS_LIMIT_ENV, raising=False)
        yield
        set_limit_override(TASKS_LIMIT_ENV, None)
        set_limit_override(TAGS_LIMIT_ENV, None)

    def test_cli_values_are_registered_as_overrides(self):
        from morgenmcp.client import TAGS_LIMIT_ENV, TASKS_LIMIT_ENV, resolve_limit
        from morgenmcp.server import _apply_limit_config

        _apply_limit_config(cli_tasks_limit=30, cli_tags_limit=60)

        assert resolve_limit(None, TASKS_LIMIT_ENV, 100, 100) == 30
        assert resolve_limit(None, TAGS_LIMIT_ENV, None, None) == 60

    def test_omitted_cli_values_clear_previous_overrides(self):
        """Calling twice must not leave a stale override behind."""
        from morgenmcp.client import TASKS_LIMIT_ENV, resolve_limit
        from morgenmcp.server import _apply_limit_config

        _apply_limit_config(cli_tasks_limit=30)
        _apply_limit_config()

        assert resolve_limit(None, TASKS_LIMIT_ENV, 100, 100) == 100

    def test_cli_tasks_limit_above_max_rejected(self):
        from morgenmcp.server import _apply_limit_config

        with pytest.raises(ValueError, match=r"--tasks-limit must be <= 100"):
            _apply_limit_config(cli_tasks_limit=101)

    def test_cli_tasks_limit_below_one_rejected(self):
        from morgenmcp.server import _apply_limit_config

        with pytest.raises(ValueError, match=r"--tasks-limit must be >= 1"):
            _apply_limit_config(cli_tasks_limit=0)

    def test_cli_tags_limit_has_no_upper_bound(self):
        """tags.mdx documents no maximum, so a large value is legal."""
        from morgenmcp.client import TAGS_LIMIT_ENV, resolve_limit
        from morgenmcp.server import _apply_limit_config

        _apply_limit_config(cli_tags_limit=9999)
        assert resolve_limit(None, TAGS_LIMIT_ENV, None, None) == 9999

    def test_bad_env_var_rejected_at_startup(self, monkeypatch):
        """A bad env var fails during config, not on the first list call."""
        from morgenmcp.client import TASKS_LIMIT_ENV
        from morgenmcp.server import _apply_limit_config

        monkeypatch.setenv(TASKS_LIMIT_ENV, "9000")
        with pytest.raises(ValueError, match="must be <= 100"):
            _apply_limit_config()

    def test_cli_flags_are_exposed(self):
        """--tasks-limit / --tags-limit appear in the parser."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "morgenmcp.server", "--help"],
            capture_output=True,
            text=True,
        )
        assert "--tasks-limit" in result.stdout
        assert "--tags-limit" in result.stdout
