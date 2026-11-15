"""MCP protocol-level tests using FastMCP in-memory Client."""

import asyncio
import base64
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import respx
from fastmcp import Client
from fastmcp.client.logging import LogMessage
from mcp.types import TextContent, TextResourceContents

from morgenmcp.client import MorgenClient
from morgenmcp.models import Calendar, MorgenAPIError
from morgenmcp.server import mcp
from morgenmcp.tools.id_registry import clear_registry


def _structured(result: Any) -> dict[str, Any]:
    """Narrow ``CallToolResult.structured_content`` (``dict | None``) for typing."""
    assert result.structured_content is not None
    return result.structured_content


def _text(content: Any) -> str:
    """Return the text of one tool-result or resource content block."""
    assert isinstance(content, TextContent | TextResourceContents), type(content)
    return content.text


@pytest.fixture(autouse=True)
def _use_tmp_data_dir(tmp_path, monkeypatch):
    """Point persistent store at a temp directory during MCP protocol tests."""
    monkeypatch.setenv("MORGENMCP_DATA_DIR", str(tmp_path))
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
async def isolated_response_cache():
    """Evict cached MCP reads between tests that use the same calls.

    Use keys() and delete() because destroy() clears collection setup and
    breaks subsequent cache writes.
    """
    from fastmcp.server.middleware.caching import ResponseCachingMiddleware

    cache_mw = next(
        m for m in mcp.middleware if isinstance(m, ResponseCachingMiddleware)
    )
    backend = cache_mw._backend

    async def clear():
        for collection in ("tools/call", "resources/read"):
            for key in await backend.keys(collection=collection):  # pyright: ignore[reportAttributeAccessIssue]
                await backend.delete(collection=collection, key=key)

    await clear()
    yield
    await clear()


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
                "morgen_get_tag",
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
                "morgen_get_tag",
            ]:
                annotations = by_name[name].annotations
                assert annotations is not None
                assert annotations.readOnlyHint is True

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
                annotations = by_name[name].annotations
                assert annotations is not None
                assert annotations.destructiveHint is True

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
                annotations = by_name[name].annotations
                assert annotations is not None
                assert annotations.readOnlyHint is False

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

    async def test_list_tasks_output_matches_schema_for_live_shapes(self):
        """A reordered, scheduled task passes the tool's output schema."""
        from morgenmcp.models import Task, TasksListResponse

        task = Task.model_validate(
            {
                "id": "task_1",
                "title": "Reordered and scheduled",
                "position": 1.5,
                "morgen.so:derived": {"scheduled": True},
            }
        )
        with patch("morgenmcp.tools.tasks.get_client") as mock:
            client_mock = AsyncMock()
            data = TasksListResponse(tasks=[task])
            client_mock.list_tasks_and_spaces.return_value = (
                data,
                100,
            )
            mock.return_value = client_mock

            async with Client(mcp) as client:
                result = await client.call_tool("morgen_list_tasks", {})

        item = _structured(result)["tasks"][0]
        assert item["position"] == 1.5
        assert item["scheduled"] is True

    @pytest.mark.usefixtures("isolated_response_cache")
    @pytest.mark.parametrize("limit", [3, 100])
    async def test_task_coverage_counts_rows_before_filtering(self, monkeypatch, limit):
        monkeypatch.setenv("MORGENMCP_TASKS_LIMIT", str(limit))
        with respx.mock as api:
            route = api.get(
                host="api.morgen.so", path="/v3/tasks/list", params={"limit": limit}
            ).respond(
                json={
                    "data": {
                        "tasks": [
                            {"id": "fetched", "taskListId": "first"},
                            {
                                "id": "closed",
                                "taskListId": "third",
                                "progress": "completed",
                            },
                            {"id": "deleted", "taskListId": "third", "deleted": True},
                        ],
                        "spaces": [
                            {"id": "first", "name": "First"},
                            {"id": "second", "name": "Second"},
                        ],
                    }
                }
            )
            async with MorgenClient(api_key="test-key") as upstream:
                with (
                    patch("morgenmcp.tools.tasks.get_client", return_value=upstream),
                    patch("morgenmcp.resources.get_client", return_value=upstream),
                ):
                    async with Client(mcp) as client:
                        lists = (
                            await client.call_tool("morgen_list_task_lists", {})
                        ).structured_content
                        assert lists is not None
                        second = next(
                            item
                            for item in lists["task_lists"]
                            if item["name"] == "Second"
                        )
                        filtered = (
                            await client.call_tool(
                                "morgen_list_tasks", {"task_list_id": second["id"]}
                            )
                        ).structured_content
                        assert filtered is not None
                        open_contents = (await client.read_resource("morgen://tasks"))[
                            0
                        ]
                        today_contents = (
                            await client.read_resource("morgen://tasks/today")
                        )[0]
                        assert isinstance(open_contents, TextResourceContents)
                        assert isinstance(today_contents, TextResourceContents)
                        opened = json.loads(open_contents.text)
                        today = json.loads(today_contents.text)

        coverage = {
            "fetch_limit": limit,
            "limit_reached": limit == 3,
        }
        assert route.call_count == 4
        assert lists["count"] == 3
        assert {item["name"]: item["task_count"] for item in lists["task_lists"]} == {
            "First": 1,
            "Second": 0,
            "Unnamed list": 0,
        }
        assert second["task_count"] == 0
        assert opened["count"] == 1
        assert filtered["count"] == today["count"] == 0
        for payload in (lists, filtered, opened, today):
            assert payload["coverage"] == coverage

    @pytest.mark.usefixtures("isolated_response_cache")
    @pytest.mark.parametrize("limit", [None, 1, 2])
    async def test_tag_coverage_is_present_only_for_bounded_fetches(
        self, monkeypatch, limit
    ):
        monkeypatch.delenv("MORGENMCP_TAGS_LIMIT", raising=False)
        if limit is not None:
            monkeypatch.setenv("MORGENMCP_TAGS_LIMIT", str(limit))
        with respx.mock as api:
            route = api.get(host="api.morgen.so", path="/v3/tags/list").respond(
                json=[{"id": "tag", "name": "Work"}]
            )
            async with MorgenClient(api_key="test-key") as upstream:
                with (
                    patch("morgenmcp.tools.tags.get_client", return_value=upstream),
                    patch("morgenmcp.resources.get_client", return_value=upstream),
                ):
                    async with Client(mcp) as client:
                        tool = (
                            await client.call_tool("morgen_list_tags", {})
                        ).structured_content
                        contents = (await client.read_resource("morgen://tags"))[0]
                        assert isinstance(contents, TextResourceContents)
                        resource = json.loads(contents.text)

        assert route.call_count == 2
        expected_params = {} if limit is None else {"limit": str(limit)}
        assert all(
            dict(call.request.url.params) == expected_params for call in route.calls
        )
        assert tool == resource
        assert resource["count"] == 1
        if limit is None:
            assert "coverage" not in resource
        else:
            assert resource["coverage"] == {
                "fetch_limit": limit,
                "limit_reached": limit == 1,
            }

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
            body = json.loads(_text(payload[0]))
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
        text = _text(result.content[0])
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
                payload = json.loads(_text(contents[0]))
                assert payload == {"accounts": [], "count": 0}


@pytest.mark.usefixtures("isolated_response_cache")
class TestTypedOutputSchemas:
    """The typed TypedDict returns give each tool a shaped outputSchema, and
    FastMCP validates every return against it at runtime.

    These tests lock in the ``NotRequired`` decisions in ``tools/outputs.py``:
    fields that ``filter_none_values`` can drop MUST stay optional, or a normal
    sparse response would raise ``Output validation error`` in production. A
    future change that over-tightens a field to *required* fails here instead.
    """

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
        payload = _structured(result)
        assert payload["count"] == 1
        item = payload["accounts"][0]
        assert item["email"] == "user@example.com"
        assert "displayName" not in item  # filtered, and validation allowed it

    async def test_sparse_event_passes_output_validation(self):
        """An event with no morgen.so:metadata must still validate.

        ``progress``/``canBeCompleted``/``isAutoScheduled`` are dropped entirely
        by ``filter_none_values`` when there is no metadata object, so they must
        be ``NotRequired`` in ``EventItem``. A future change tightening any of
        them to required fails here rather than in production.
        """
        from morgenmcp.models import Event
        from morgenmcp.tools.id_registry import register_id

        real_cal_id = (
            base64.b64encode(
                json.dumps(
                    ["e" * 24, "sparse@example.com"], separators=(",", ":")
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        real_evt_id = (
            base64.b64encode(
                json.dumps(
                    ["sparse@example.com", "evt_sparse", "e" * 24],
                    separators=(",", ":"),
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        virtual_cal_id = register_id(real_cal_id)

        event = Event(
            id=real_evt_id,
            calendar_id=real_cal_id,
            account_id="e" * 24,
            integration_id="google",
            title="Bare",
            start="2025-06-02T10:00:00",
            duration="PT1H",
        )

        with patch("morgenmcp.tools.events.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.list_events.return_value = [event]
            mock.return_value = client_mock

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "morgen_list_events",
                    {
                        "start": "2025-06-02T00:00:00",
                        "end": "2025-06-03T00:00:00",
                        "calendar_ids": [virtual_cal_id],
                    },
                )

        assert result.is_error is False
        item = _structured(result)["events"][0]
        assert item["title"] == "Bare"
        # filtered out, and validation allowed it
        assert "progress" not in item
        assert "canBeCompleted" not in item
        assert "isAutoScheduled" not in item

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
        updated = _structured(result)["updated"]
        assert updated["busy"] is False
        assert updated["overrideColor"] is None
        assert updated["overrideName"] is None

    # Live /tasks/list shape, synthetic values. `links` was never seen live,
    # so it uses the JSCalendar (RFC 8984) Link shape.
    _LIVE_TASK = {
        "@type": "Task",
        "id": "task-live-shape",
        "integrationId": "morgen",
        "taskListId": "default",
        "title": "Live-shaped task",
        "priority": 0,
        "progress": "needs-action",
        "position": 1768469400000,
        "tags": [],
        "created": "2026-01-15T09:30:00Z",
        "updated": "2026-01-15T09:30:00Z",
        "morgen.so:derived": {"scheduled": True},
        "links": {"link-1": {"@type": "Link", "href": "https://example.com/spec"}},
    }

    async def _mocked_task_call(
        self,
        monkeypatch,
        tool: str,
        args: dict,
        *,
        list_tasks: list[dict] | None = None,
        single_task: dict | None = None,
    ) -> dict:
        """Execute a task tool against a respx-mocked Morgen API.

        Only HTTP is mocked, so the real client, envelope parse, ``Task`` model,
        ``_format_task`` and output-schema validation all run.
        """
        from morgenmcp import client as client_module

        monkeypatch.setattr(
            client_module, "_client", client_module.MorgenClient(api_key="test-key")
        )
        with respx.mock(assert_all_called=False) as api:
            api.get(host="api.morgen.so", path="/v3/tasks/list").respond(
                json={
                    "data": {
                        "tasks": list_tasks or [],
                        "labelDefs": [],
                        "spaces": [],
                    }
                }
            )
            api.get(host="api.morgen.so", path="/v3/tasks").respond(
                json={"data": {"task": single_task, "labelDefs": []}}
            )
            async with Client(mcp) as client:
                result = await client.call_tool(tool, args, raise_on_error=False)

        assert result.is_error is False, _text(result.content[0])
        return _structured(result)

    async def test_incremental_listing_preserves_completed_and_deleted_tasks(
        self, monkeypatch
    ):
        payload = await self._mocked_task_call(
            monkeypatch,
            "morgen_list_tasks",
            {"limit": 2, "updated_after": "2000-01-01T00:00:00Z"},
            list_tasks=[
                {"id": "completed-task", "progress": "completed"},
                {"id": "deleted-task", "deleted": True},
            ],
        )
        assert payload["count"] == 2
        assert payload["tasks"][0]["progress"] == "completed"
        assert payload["tasks"][1]["deleted"] is True
        assert payload["coverage"] == {"fetch_limit": 2, "limit_reached": True}

    async def _call_task_tool(self, monkeypatch, tool: str, task: dict) -> dict:
        """Serve ``task`` from a respx-mocked Morgen API and return the tool's item."""
        from morgenmcp.tools.id_registry import register_id

        args = (
            {"task_id": register_id(task["id"])}
            if tool == "morgen_get_task"
            else {"limit": 5}
        )
        payload = await self._mocked_task_call(
            monkeypatch, tool, args, list_tasks=[task], single_task=task
        )
        return payload["tasks"][0] if tool == "morgen_list_tasks" else payload["task"]

    @pytest.mark.parametrize("tool", ["morgen_list_tasks", "morgen_get_task"])
    @pytest.mark.parametrize(
        ("field", "json_type"),
        [
            ("position", "number"),
            ("scheduled", "boolean"),
            ("deleted", "boolean"),
        ],
    )
    async def test_task_item_schema_types(self, tool, field, json_type):
        """Both task tools advertise the JSON types Morgen actually sends."""
        async with Client(mcp) as client:
            by_name = {t.name: t for t in await client.list_tools()}
        schema = by_name[tool].outputSchema
        assert schema is not None
        props = schema["properties"]
        item = props["tasks"]["items"] if tool == "morgen_list_tasks" else props["task"]
        assert item["properties"][field]["type"] == json_type

    @pytest.mark.parametrize("tool", ["morgen_list_tasks", "morgen_get_task"])
    async def test_live_shaped_task_passes_output_validation(self, monkeypatch, tool):
        """A scheduled task in the live /tasks/list shape validates end to end."""
        item = await self._call_task_tool(monkeypatch, tool, self._LIVE_TASK)

        assert item["scheduled"] is True

    @pytest.mark.parametrize("tool", ["morgen_list_tasks", "morgen_get_task"])
    @pytest.mark.parametrize(
        ("position", "json_type"),
        [(1713627622646, int), (1713627622646.5, float)],  # fractional value from #3
        ids=["integer", "fractional"],
    )
    async def test_task_position_keeps_its_json_type(
        self, monkeypatch, tool, position, json_type
    ):
        """Integer positions stay integers, and fractional ones are accepted.

        Compares with ``type(...) is``, not ``==``: ``1713627622646.0`` equals
        ``1713627622646`` in Python but renders differently to clients. The
        task carries no ``morgen.so:derived``, so position is all it tests.
        """
        task = {k: v for k, v in self._LIVE_TASK.items() if k != "morgen.so:derived"}
        item = await self._call_task_tool(
            monkeypatch, tool, {**task, "position": position}
        )

        assert item["position"] == position
        assert type(item["position"]) is json_type

    async def test_get_task_deleted_passes_output_validation(self, monkeypatch):
        """A soft-deleted task returns with deleted: True and passes output validation."""
        item = await self._call_task_tool(
            monkeypatch, "morgen_get_task", {**self._LIVE_TASK, "deleted": True}
        )
        assert item["deleted"] is True

    @staticmethod
    def _deref_schema(root: dict, node: dict) -> dict:
        while "$ref" in node:
            ref = node["$ref"]
            assert ref.startswith("#/$defs/"), f"Unexpected schema ref: {ref}"
            node = root["$defs"][ref.removeprefix("#/$defs/")]
        return node

    @pytest.mark.parametrize("tool", ["morgen_list_tasks", "morgen_get_task"])
    async def test_task_relation_schema_type(self, tool):
        """relatedTo.*.relation advertises a bool-valued object, not a string (#35)."""
        async with Client(mcp) as client:
            by_name = {t.name: t for t in await client.list_tools()}
        schema = by_name[tool].outputSchema
        assert schema is not None
        props = schema["properties"]
        item = self._deref_schema(
            schema,
            props["tasks"]["items"] if tool == "morgen_list_tasks" else props["task"],
        )
        related_to = self._deref_schema(schema, item["properties"]["relatedTo"])
        rel_ref = self._deref_schema(schema, related_to["additionalProperties"])
        rel_prop = self._deref_schema(schema, rel_ref["properties"]["relation"])
        assert rel_prop["type"] == "object"
        assert rel_prop["additionalProperties"] == {"type": "boolean"}

    @pytest.mark.parametrize("tool", ["morgen_list_tasks", "morgen_get_task"])
    @pytest.mark.parametrize(
        ("raw_related_to", "expected_relations"),
        [
            (
                {
                    "parent-raw-1": {
                        "@type": "Relation",
                        "relation": {"parent": True},
                    }
                },
                {"parent-raw-1": {"relation": {"parent": True}}},
            ),
            (
                {
                    "parent-raw-1": {
                        "@type": "Relation",
                        "relation": {"parent": True, "child": False},
                    },
                    "prev-raw-1": {
                        "@type": "Relation",
                        "relation": {"next": True},
                    },
                },
                {
                    "parent-raw-1": {"relation": {"parent": True, "child": False}},
                    "prev-raw-1": {"relation": {"next": True}},
                },
            ),
            (
                {"parent-raw-1": {"@type": "Relation"}},
                {"parent-raw-1": {"relation": {}}},
            ),
        ],
        ids=["parent", "multi_and_false_flags", "omitted_relation_defaults_empty"],
    )
    async def test_task_with_relations_passes_output_validation(
        self, monkeypatch, tool, raw_related_to, expected_relations
    ):
        """Subtasks and multi-relation tasks pass output validation with virtualized keys (#35)."""
        from morgenmcp.tools.id_registry import register_id, resolve_id

        item = await self._call_task_tool(
            monkeypatch, tool, {**self._LIVE_TASK, "relatedTo": raw_related_to}
        )

        expected_virtual = {
            register_id(raw_id): val for raw_id, val in expected_relations.items()
        }
        assert item["relatedTo"] == expected_virtual
        for raw_id, vid in ((r, register_id(r)) for r in expected_relations):
            assert raw_id not in item["relatedTo"]
            assert len(vid) == 7
            assert resolve_id(vid) == raw_id

    @pytest.mark.parametrize("tool", ["morgen_list_tasks", "morgen_get_task"])
    async def test_task_empty_related_to_is_omitted(self, monkeypatch, tool):
        """An empty relatedTo map is filtered out rather than emitted as {}."""
        item = await self._call_task_tool(
            monkeypatch, tool, {**self._LIVE_TASK, "relatedTo": {}}
        )
        assert "relatedTo" not in item

    async def test_list_tasks_with_mixed_parent_and_subtask(self, monkeypatch):
        """A single subtask must not break a whole morgen_list_tasks listing (#35)."""
        parent = {
            **self._LIVE_TASK,
            "id": "parent-raw-100",
            "title": "Parent task",
        }
        subtask = {
            **self._LIVE_TASK,
            "id": "child-raw-200",
            "title": "Subtask",
            "relatedTo": {
                "parent-raw-100": {
                    "@type": "Relation",
                    "relation": {"parent": True},
                }
            },
        }
        payload = await self._mocked_task_call(
            monkeypatch,
            "morgen_list_tasks",
            {"limit": 10},
            list_tasks=[parent, subtask],
        )
        assert payload["count"] == 2
        parent_out, subtask_out = payload["tasks"]
        assert "relatedTo" not in parent_out
        assert subtask_out["relatedTo"] == {
            parent_out["id"]: {"relation": {"parent": True}}
        }

    async def test_create_subtask_round_trips_through_list_tasks(self, monkeypatch):
        """A subtask payload sent by morgen_create_task validates when read back (#35)."""
        import httpx

        from morgenmcp import client as client_module
        from morgenmcp.tools.id_registry import register_id

        monkeypatch.setattr(
            client_module, "_client", client_module.MorgenClient(api_key="test-key")
        )
        parent_vid = register_id("parent-roundtrip-1")
        created_bodies: list[dict] = []

        def _create_handler(request):
            body = json.loads(request.content.decode())
            created_bodies.append(body)
            return httpx.Response(200, json={"data": {"id": "child-roundtrip-2"}})

        def _list_handler(_request):
            sent = created_bodies[-1]
            echoed = {
                **self._LIVE_TASK,
                "id": "child-roundtrip-2",
                "title": sent["title"],
                "relatedTo": sent["relatedTo"],
            }
            return httpx.Response(
                200, json={"data": {"tasks": [echoed], "labelDefs": [], "spaces": []}}
            )

        with respx.mock(assert_all_called=False) as api:
            api.post(host="api.morgen.so", path="/v3/tasks/create").mock(
                side_effect=_create_handler
            )
            api.get(host="api.morgen.so", path="/v3/tasks/list").mock(
                side_effect=_list_handler
            )
            async with Client(mcp) as client:
                create_res = await client.call_tool(
                    "morgen_create_task",
                    {"title": "Subtask", "parent_task_id": parent_vid},
                    raise_on_error=False,
                )
                assert create_res.is_error is False, _text(create_res.content[0])
                list_res = await client.call_tool(
                    "morgen_list_tasks", {"limit": 5}, raise_on_error=False
                )

        assert list_res.is_error is False, _text(list_res.content[0])
        listed = _structured(list_res)["tasks"][0]
        assert listed["relatedTo"] == {parent_vid: {"relation": {"parent": True}}}

    async def test_get_task_unknown_returns_tool_error(self, monkeypatch):
        """When Morgen API returns data.task = null, morgen_get_task returns a clean ToolError."""
        from morgenmcp import client as client_module
        from morgenmcp.tools.id_registry import register_id

        monkeypatch.setattr(
            client_module, "_client", client_module.MorgenClient(api_key="test-key")
        )
        task_id = "fb0ff56a-24f0-40d0-844a-14c6de79c576"
        virtual_id = register_id(task_id)

        with respx.mock(assert_all_called=False) as api:
            api.get(host="api.morgen.so", path="/v3/tasks").respond(
                json={"data": {"task": None, "labelDefs": []}}
            )
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "morgen_get_task", {"task_id": virtual_id}, raise_on_error=False
                )

        assert result.is_error is True
        text = getattr(result.content[0], "text", "")
        assert f"Task with ID '{virtual_id}' not found" in text
        assert task_id not in text


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
        "morgen_get_tag",
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
        """Without read-only mode, every tool is visible."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools) == 24

    async def test_read_only_hides_mutating_tools(self):
        """After _apply_read_only, only the read tools are visible, and each
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
            assert len({t.name for t in await client.list_tools()}) == 24


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
        assert "morgen_get_tag" in included
        # `morgen_get_task` and writes must NOT be in the allowlist
        assert "morgen_get_task" not in included, (
            "morgen_get_task must not be cached (breaks post-mutation verification)"
        )
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

    async def test_get_task_is_not_cached_after_mutation(self):
        """morgen_get_task bypasses the 60s cache so post-delete reads see deleted=True."""
        from morgenmcp.models import Task
        from morgenmcp.tools.id_registry import register_id

        real_id = "task-uncached-after-delete"
        virtual_id = register_id(real_id)
        active = Task(id=real_id, title="Verify me")
        deleted = Task(id=real_id, title="Verify me", deleted=True)

        with patch("morgenmcp.tools.tasks.get_client") as mock:
            client_mock = AsyncMock()
            client_mock.get_task.side_effect = [active, deleted]
            mock.return_value = client_mock

            async with Client(mcp) as client:
                before = await client.call_tool(
                    "morgen_get_task", {"task_id": virtual_id}
                )
                await client.call_tool("morgen_delete_task", {"task_id": virtual_id})
                after = await client.call_tool(
                    "morgen_get_task", {"task_id": virtual_id}
                )

            assert client_mock.get_task.await_count == 2
            assert _structured(before)["task"].get("deleted") is None
            assert _structured(after)["task"]["deleted"] is True

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
            client_mock.list_tags.return_value = ([], None)
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

    @pytest.mark.usefixtures("isolated_response_cache")
    async def test_event_writes_invalidate_list_events_and_resources_only(self):
        """Event writes evict cached list_events & event resources, not unrelated tools."""
        from morgenmcp.models import CreatedEventInfo, Event, EventCreateResponse
        from morgenmcp.tools.id_registry import register_id

        acc_id = "d" * 24
        real_cal_id = (
            base64.b64encode(
                json.dumps([acc_id, "inv@example.com"], separators=(",", ":")).encode()
            )
            .decode()
            .rstrip("=")
        )
        real_evt_id = (
            base64.b64encode(
                json.dumps(
                    ["inv@example.com", "evt_inv", acc_id], separators=(",", ":")
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        virtual_cal_id = register_id(real_cal_id)
        created_evt = Event(
            id=real_evt_id,
            calendar_id=real_cal_id,
            account_id=acc_id,
            integration_id="google",
            title="Job search",
            start="2026-11-14T13:00:00",
            duration="PT45M",
            time_zone="America/Chicago",
        )
        updated_evt = created_evt.model_copy(update={"title": "Job search (updated)"})

        list_args = {
            "start": "2026-11-14T12:00:00",
            "end": "2026-11-14T16:00:00",
            "time_zone": "America/Chicago",
            "calendar_ids": [virtual_cal_id],
            "compact": True,
        }

        with (
            patch("morgenmcp.tools.events.get_client") as events_mock,
            patch("morgenmcp.tools.accounts.get_client") as accounts_mock,
            patch("morgenmcp.resources.get_client") as resources_mock,
        ):
            evt_client = AsyncMock()
            evt_client.list_events.side_effect = [
                [],
                [created_evt],
                [updated_evt],
                [],
            ]
            evt_client.create_event.return_value = EventCreateResponse(
                event=CreatedEventInfo(
                    id=real_evt_id, calendar_id=real_cal_id, account_id=acc_id
                )
            )
            events_mock.return_value = evt_client

            acc_client = AsyncMock()
            acc_client.list_accounts.return_value = []
            accounts_mock.return_value = acc_client

            res_client = AsyncMock()
            res_client.list_calendars.return_value = []
            res_client.list_events.return_value = []
            resources_mock.return_value = res_client

            async with Client(mcp) as client:
                # Populate list_accounts, events/today resource, and list_events caches
                await client.call_tool("morgen_list_accounts", {})
                await client.read_resource("morgen://events/today")
                before = await client.call_tool("morgen_list_events", list_args)
                assert before.structured_content is not None
                assert before.structured_content["count"] == 0

                # Create invalidates list_events & events/today, NOT list_accounts
                created = await client.call_tool(
                    "morgen_create_event",
                    {
                        "calendar_id": virtual_cal_id,
                        "title": "Job search",
                        "start": "2026-11-14T13:00:00",
                        "duration": "PT45M",
                        "time_zone": "America/Chicago",
                    },
                )
                assert created.structured_content is not None
                virtual_evt_id = created.structured_content["event"]["id"]

                after_create = await client.call_tool("morgen_list_events", list_args)
                assert after_create.structured_content is not None
                assert after_create.structured_content["count"] == 1
                assert "Job search" in after_create.structured_content["events"][0]

                # list_accounts stays cached across the event write
                await client.call_tool("morgen_list_accounts", {})
                assert acc_client.list_accounts.await_count == 1

                # events/today resource cache was evicted by the event write
                await client.read_resource("morgen://events/today")
                assert res_client.list_calendars.await_count == 2

                # Update invalidates list_events cache
                await client.call_tool(
                    "morgen_update_event",
                    {"event_id": virtual_evt_id, "title": "Job search (updated)"},
                )
                after_update = await client.call_tool("morgen_list_events", list_args)
                assert after_update.structured_content is not None
                assert (
                    "Job search (updated)"
                    in after_update.structured_content["events"][0]
                )

                # Delete invalidates list_events cache
                await client.call_tool(
                    "morgen_delete_event", {"event_id": virtual_evt_id}
                )
                after_delete = await client.call_tool("morgen_list_events", list_args)
                assert after_delete.structured_content is not None
                assert after_delete.structured_content["count"] == 0

            assert evt_client.list_events.await_count == 4

    async def test_tracked_store_prunes_expired_keys(self, monkeypatch):
        """Expired tracked cache keys are pruned on subsequent puts."""
        from morgenmcp.server import _ACTIVE_CACHE_TARGET, _TrackedMemoryStore

        now = 1000.0
        monkeypatch.setattr("morgenmcp.server.time.monotonic", lambda: now)
        store = _TrackedMemoryStore()

        token = _ACTIVE_CACHE_TARGET.set(("tools/call", "morgen_list_events"))
        try:
            await store.put("k1", {"v": 1}, collection="tools/call", ttl=60)
            assert set(store._tracked_keys[("tools/call", "morgen_list_events")]) == {
                "k1"
            }

            now = 1061.0  # past TTL
            await store.put("k2", {"v": 2}, collection="tools/call", ttl=60)
            assert set(store._tracked_keys[("tools/call", "morgen_list_events")]) == {
                "k2"
            }
        finally:
            _ACTIVE_CACHE_TARGET.reset(token)

    @pytest.mark.usefixtures("isolated_response_cache")
    async def test_overlapping_write_rejects_stale_read_cache_insertion(self):
        """A delayed read overlapping a write must not poison the response cache."""
        from morgenmcp.models import CreatedEventInfo, Event, EventCreateResponse
        from morgenmcp.tools.id_registry import register_id

        acc_id = "e" * 24
        real_cal_id = (
            base64.b64encode(
                json.dumps([acc_id, "race@example.com"], separators=(",", ":")).encode()
            )
            .decode()
            .rstrip("=")
        )
        real_evt_id = (
            base64.b64encode(
                json.dumps(
                    ["race@example.com", "evt_race", acc_id], separators=(",", ":")
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        virtual_cal_id = register_id(real_cal_id)
        created_evt = Event(
            id=real_evt_id,
            calendar_id=real_cal_id,
            account_id=acc_id,
            integration_id="google",
            title="Overlap event",
            start="2026-11-14T13:00:00",
            duration="PT45M",
            time_zone="America/Chicago",
        )
        list_args = {
            "start": "2026-11-14T12:00:00",
            "end": "2026-11-14T16:00:00",
            "time_zone": "America/Chicago",
            "calendar_ids": [virtual_cal_id],
            "compact": True,
        }

        read_entered = asyncio.Event()
        release_read = asyncio.Event()
        calls = 0

        async def _list_events(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                read_entered.set()
                await release_read.wait()
                return []
            return [created_evt]

        with patch("morgenmcp.tools.events.get_client") as events_mock:
            evt_client = AsyncMock()
            evt_client.list_events.side_effect = _list_events
            evt_client.create_event.return_value = EventCreateResponse(
                event=CreatedEventInfo(
                    id=real_evt_id, calendar_id=real_cal_id, account_id=acc_id
                )
            )
            events_mock.return_value = evt_client

            async with Client(mcp) as client:
                stale_task = asyncio.create_task(
                    client.call_tool("morgen_list_events", list_args)
                )
                await read_entered.wait()

                await client.call_tool(
                    "morgen_create_event",
                    {
                        "calendar_id": virtual_cal_id,
                        "title": "Overlap event",
                        "start": "2026-11-14T13:00:00",
                        "duration": "PT45M",
                        "time_zone": "America/Chicago",
                    },
                )
                release_read.set()
                stale_res = await stale_task
                assert stale_res.structured_content is not None
                assert stale_res.structured_content["count"] == 0

                fresh_res = await client.call_tool("morgen_list_events", list_args)
                assert fresh_res.structured_content is not None
                assert fresh_res.structured_content["count"] == 1
                assert "Overlap event" in fresh_res.structured_content["events"][0]

            assert calls == 2

    @pytest.mark.usefixtures("isolated_response_cache")
    async def test_partial_failure_and_all_account_failure_not_cached(self):
        """Failed and partial cross-account queries are never cached."""
        from fastmcp.exceptions import ToolError

        from morgenmcp.models import Event
        from morgenmcp.tools.id_registry import register_id

        acc1 = "f" * 24
        acc2 = "1" * 24
        cal1_id = (
            base64.b64encode(
                json.dumps([acc1, "a@example.com"], separators=(",", ":")).encode()
            )
            .decode()
            .rstrip("=")
        )
        cal2_id = (
            base64.b64encode(
                json.dumps([acc2, "b@example.com"], separators=(",", ":")).encode()
            )
            .decode()
            .rstrip("=")
        )
        vcal1 = register_id(cal1_id)
        vcal2 = register_id(cal2_id)
        evt2_id = (
            base64.b64encode(
                json.dumps(
                    ["b@example.com", "rec1", acc2], separators=(",", ":")
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        recovered_evt = Event(
            id=evt2_id,
            calendar_id=cal2_id,
            account_id=acc2,
            integration_id="google",
            title="Recovered",
            start="2026-11-14T13:00:00",
            duration="PT30M",
            time_zone="America/Chicago",
        )
        list_args = {
            "start": "2026-11-14T12:00:00",
            "end": "2026-11-14T16:00:00",
            "time_zone": "America/Chicago",
            "calendar_ids": [vcal1, vcal2],
            "compact": True,
        }

        tool_phase = 0

        async def _tool_list_events(*, account_id, **_kwargs):
            if tool_phase == 0:
                raise MorgenAPIError("Service Unavailable", status_code=503)
            if tool_phase == 1:
                if account_id == acc2:
                    raise MorgenAPIError("Service Unavailable", status_code=503)
                return []
            return [recovered_evt] if account_id == acc2 else []

        res_phase = 0

        async def _res_list_events(*, account_id, **_kwargs):
            if res_phase == 0 and account_id == acc2:
                raise MorgenAPIError("Service Unavailable", status_code=503)
            return [recovered_evt] if account_id == acc2 else []

        with (
            patch("morgenmcp.tools.events.get_client") as events_mock,
            patch("morgenmcp.resources.get_client") as resources_mock,
        ):
            evt_client = AsyncMock()
            evt_client.list_events.side_effect = _tool_list_events
            events_mock.return_value = evt_client

            res_client = AsyncMock()
            res_client.list_calendars.return_value = [
                Calendar(id=cal1_id, account_id=acc1, integration_id="google"),
                Calendar(id=cal2_id, account_id=acc2, integration_id="google"),
            ]
            res_client.list_events.side_effect = _res_list_events
            resources_mock.return_value = res_client

            async with Client(mcp) as client:
                with pytest.raises(ToolError, match="all accounts"):
                    await client.call_tool("morgen_list_events", list_args)

                tool_phase = 1
                partial_res = await client.call_tool("morgen_list_events", list_args)
                assert partial_res.structured_content is not None
                assert partial_res.structured_content["count"] == 0

                tool_phase = 2
                recovered_res = await client.call_tool("morgen_list_events", list_args)
                assert recovered_res.structured_content is not None
                assert recovered_res.structured_content["count"] == 1
                assert "Recovered" in recovered_res.structured_content["events"][0]

                # Partial resource read is also not cached
                res_partial = await client.read_resource("morgen://events/upcoming")
                assert isinstance(res_partial[0], TextResourceContents)
                assert json.loads(res_partial[0].text)["count"] == 0

                res_phase = 1
                res_recovered = await client.read_resource("morgen://events/upcoming")
                assert isinstance(res_recovered[0], TextResourceContents)
                assert json.loads(res_recovered[0].text)["count"] == 1


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
