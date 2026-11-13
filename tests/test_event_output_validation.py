"""Regression coverage for sparse nested event fields through the MCP protocol."""

from __future__ import annotations

import base64
import json

import pytest
import respx
from fastmcp import Client
from pydantic import BaseModel

from morgenmcp import client as client_module
from morgenmcp.server import mcp
from morgenmcp.tools.id_registry import clear_registry, register_id


@pytest.mark.parametrize(
    "nested, expected",
    [
        (
            {
                "participants": {
                    "p": {"email": "owner@example.com", "roles": {"owner": True}}
                }
            },
            {
                "participants": [
                    {
                        "email": "owner@example.com",
                        "status": "needs-action",
                        "isOrganizer": True,
                    }
                ]
            },
        ),
        (
            {"participants": {"p": {"name": "Guest"}}},
            {
                "participants": [
                    {"name": "Guest", "status": "needs-action", "isOrganizer": False}
                ]
            },
        ),
        (
            {"locations": {"l": {"@type": "Location", "name": None}}},
            {"locations": [{}]},
        ),
        (
            {"participants": {"p": {"name": None, "email": None}}},
            {"participants": [{"status": "needs-action", "isOrganizer": False}]},
        ),
        (
            {
                "participants": {
                    "p": {"email": "owner@example.com"},
                    "q": {
                        "name": "Guest",
                        "email": "guest@example.com",
                        "participationStatus": "accepted",
                    },
                }
            },
            {
                "participants": [
                    {
                        "email": "owner@example.com",
                        "status": "needs-action",
                        "isOrganizer": False,
                    },
                    {
                        "name": "Guest",
                        "email": "guest@example.com",
                        "status": "accepted",
                        "isOrganizer": False,
                    },
                ]
            },
        ),
    ],
    ids=[
        "missing-name",
        "missing-email",
        "null-location",
        "null-participant",
        "mixed-participants",
    ],
)
async def test_list_events_sparse_nested_fields(
    monkeypatch, tmp_path, nested, expected
):
    monkeypatch.setenv("MORGENMCP_DATA_DIR", str(tmp_path))
    clear_registry()
    calendar_id = (
        base64.b64encode(
            json.dumps(["e" * 24, f"{tmp_path.name}@example.com"]).encode()
        )
        .decode()
        .rstrip("=")
    )
    event = {
        "id": "event-sparse",
        "calendarId": calendar_id,
        "accountId": "e" * 24,
        "integrationId": "google",
        "title": "Sparse event",
        "start": "2026-11-10T10:00:00",
        "duration": "PT1H",
        **nested,
    }
    async with client_module.MorgenClient(api_key="test-key") as api_client:
        monkeypatch.setattr(client_module, "_client", api_client)
        with respx.mock() as api:
            api.get(host="api.morgen.so", path="/v3/events/list").respond(
                json={"data": {"events": [event]}}
            )
            async with Client(mcp) as client:
                result = await client.call_tool(
                    "morgen_list_events",
                    {
                        "start": "2026-11-10T00:00:00",
                        "end": "2026-11-11T00:00:00",
                        "calendar_ids": [register_id(calendar_id)],
                    },
                    raise_on_error=False,
                )
    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert result.structured_content["count"] == 1
    item = result.structured_content["events"][0]
    for key, value in expected.items():
        assert item[key] == value
    clear_registry()


@pytest.mark.parametrize(
    "tool, collection, model_name, formatter_name, payload",
    [
        (
            "morgen_list_calendars",
            "calendars",
            "Calendar",
            "calendar",
            {
                "id": "calendar-contract",
                "accountId": "account-contract",
                "integrationId": "google",
                "myRights": {},
                "morgen.so:metadata": {"busy": False},
            },
        ),
        (
            "morgen_list_tasks",
            "tasks",
            "Task",
            "task",
            {
                "id": "task-contract",
                "priority": 0,
                "deleted": False,
                "morgen.so:derived": {"scheduled": False},
            },
        ),
        (
            "morgen_list_tasks",
            "tasks",
            "Task",
            "task",
            {
                "id": "task-contract",
                "morgen.so:derived": {},
            },
        ),
        (
            "morgen_list_tags",
            "tags",
            "Tag",
            "tag",
            {
                "id": "tag-contract",
                "deleted": False,
            },
        ),
        (
            "morgen_list_events",
            "events",
            "Event",
            "full_event",
            {
                "id": "event-contract",
                "calendarId": "calendar-contract",
                "accountId": "account-contract",
                "integrationId": "google",
                "start": "2026-11-10T10:00:00",
                "duration": "PT1H",
                "participants": {"p": {}},
                "locations": {"l": {}},
                "alerts": {"valid": {"trigger": {"offset": "-PT15M"}}},
                "recurrenceRules": [{"frequency": "daily"}],
            },
        ),
    ],
    ids=[
        "calendar-nesting",
        "task-false-flags",
        "task-empty-derived",
        "sparse-tag",
        "event-nesting",
    ],
)
async def test_sparse_builders_match_advertised_schema(
    tool,
    collection,
    model_name,
    formatter_name,
    payload,
):
    """Check nested output against the public schema, including legitimate false values."""
    import jsonschema

    from morgenmcp import models
    from morgenmcp.tools import calendars, events, tags, tasks

    formatters = {
        "calendar": calendars._format_calendar,
        "full_event": events._format_full_event,
        "tag": tags._format_tag,
        "task": tasks._format_task,
    }
    item = formatters[formatter_name](
        getattr(models, model_name).model_validate(payload)
    )
    async with Client(mcp) as client:
        advertised = {t.name: t for t in await client.list_tools()}
    if isinstance(item, BaseModel):
        item = item.model_dump()
    schema = advertised[tool].outputSchema
    assert schema is not None
    jsonschema.validate({collection: [item], "count": 1}, schema)
    if formatter_name == "calendar":
        assert item["metadata"] == {"busy": False}
        assert item["permissions"]["canRead"] is False
    elif formatter_name == "task" and "priority" in payload:
        assert item["priority"] == 0
        assert item["scheduled"] is False
