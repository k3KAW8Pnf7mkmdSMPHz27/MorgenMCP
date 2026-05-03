"""Unit tests for MCP resources."""

import base64
import json
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ResourceError

from morgenmcp.models import Account, Calendar, Event, Tag, Task
from morgenmcp.resources import (
    _LOCAL_DT_FMT,
    _is_open,
    _this_week_range,
    _today_range,
    _upcoming_range,
    res_account,
    res_accounts,
    res_calendar,
    res_calendar_events,
    res_calendars,
    res_events_this_week,
    res_events_today,
    res_events_upcoming,
    res_tags,
    res_tasks,
    res_tasks_today,
)
from morgenmcp.tools.id_registry import clear_registry, register_id


def _make_calendar_id(account_id: str, email: str) -> str:
    return (
        base64.b64encode(
            json.dumps([account_id, email], separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )


def _make_event_id(email: str, uid: str, account_id: str) -> str:
    return (
        base64.b64encode(
            json.dumps([email, uid, account_id], separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )


@pytest.fixture(autouse=True)
def _clear_registry():
    clear_registry()
    yield
    clear_registry()


@pytest.fixture
def mock_client():
    """Patch morgenmcp.resources.get_client to return an AsyncMock client."""
    with patch("morgenmcp.resources.get_client") as factory:
        client = AsyncMock()
        factory.return_value = client
        yield client


@pytest.fixture
def account_id() -> str:
    return "6954a6179c9d703795f281ce"


@pytest.fixture
def calendar_id(account_id) -> str:
    return _make_calendar_id(account_id, "user@example.com")


@pytest.fixture
def event_id(account_id) -> str:
    return _make_event_id("user@example.com", "evt-uid-1", account_id)


@pytest.fixture
def sample_account(account_id) -> Account:
    return Account(
        id=account_id,
        provider_id="provider-1",
        integration_id="google",
        provider_user_id="user@example.com",
        provider_user_display_name="Test User",
    )


@pytest.fixture
def sample_calendar(calendar_id, account_id) -> Calendar:
    return Calendar(
        id=calendar_id,
        account_id=account_id,
        integration_id="google",
        name="Personal",
        color="#4285f4",
        sort_order=0,
    )


@pytest.fixture
def sample_event(event_id, calendar_id, account_id) -> Event:
    return Event(
        id=event_id,
        calendar_id=calendar_id,
        account_id=account_id,
        integration_id="google",
        title="Standup",
        start="2026-05-03T09:00:00",
        duration="PT30M",
        time_zone="America/Chicago",
        show_without_time=False,
    )


# --- helper / time math ---


class TestTimeRanges:
    def test_today_range_is_midnight_to_midnight(self):
        start_s, end_s = _today_range()
        start = datetime.strptime(start_s, _LOCAL_DT_FMT)
        end = datetime.strptime(end_s, _LOCAL_DT_FMT)
        assert start.hour == 0 and start.minute == 0
        assert end - start == timedelta(days=1)
        assert start.date() == date.today()

    def test_this_week_range_is_seven_days_starting_monday(self):
        start_s, end_s = _this_week_range()
        start = datetime.strptime(start_s, _LOCAL_DT_FMT)
        end = datetime.strptime(end_s, _LOCAL_DT_FMT)
        assert start.weekday() == 0  # Monday
        assert end - start == timedelta(days=7)

    def test_upcoming_range_seven_days_default(self):
        start_s, end_s = _upcoming_range()
        start = datetime.strptime(start_s, _LOCAL_DT_FMT)
        end = datetime.strptime(end_s, _LOCAL_DT_FMT)
        assert end - start == timedelta(days=7)


class TestIsOpen:
    @pytest.mark.parametrize(
        "progress,expected",
        [
            ("needs-action", True),
            ("in-process", True),
            (None, True),
            ("completed", False),
            ("cancelled", False),
        ],
    )
    def test_is_open(self, progress, expected):
        task = Task(id="t1", title="x", progress=progress)
        assert _is_open(task) is expected


# --- account resources ---


class TestAccountResources:
    @pytest.mark.asyncio
    async def test_res_accounts_returns_compact_list(self, mock_client, sample_account):
        mock_client.list_accounts.return_value = [sample_account]
        body = json.loads(await res_accounts())
        assert body["count"] == 1
        assert body["accounts"][0]["email"] == "user@example.com"
        assert len(body["accounts"][0]["id"]) == 7  # virtual ID

    @pytest.mark.asyncio
    async def test_res_account_found(self, mock_client, sample_account, account_id):
        mock_client.list_accounts.return_value = [sample_account]
        virtual_id = register_id(account_id)
        body = json.loads(await res_account(virtual_id))
        assert body["account"]["email"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_res_account_missing_raises(self, mock_client, sample_account):
        mock_client.list_accounts.return_value = [sample_account]
        # Register a different real ID so resolve_id succeeds but lookup misses
        virtual_id = register_id("0123456789abcdef01234567")
        with pytest.raises(ResourceError, match="not found"):
            await res_account(virtual_id)


# --- calendar resources ---


class TestCalendarResources:
    @pytest.mark.asyncio
    async def test_res_calendars_returns_compact_list(
        self, mock_client, sample_calendar
    ):
        mock_client.list_calendars.return_value = [sample_calendar]
        body = json.loads(await res_calendars())
        assert body["count"] == 1
        assert body["calendars"][0]["name"] == "Personal"

    @pytest.mark.asyncio
    async def test_res_calendar_found(self, mock_client, sample_calendar, calendar_id):
        mock_client.list_calendars.return_value = [sample_calendar]
        virtual_id = register_id(calendar_id)
        body = json.loads(await res_calendar(virtual_id))
        assert body["calendar"]["name"] == "Personal"

    @pytest.mark.asyncio
    async def test_res_calendar_missing_raises(self, mock_client):
        mock_client.list_calendars.return_value = []
        virtual_id = register_id(_make_calendar_id("x" * 24, "missing@example.com"))
        with pytest.raises(ResourceError, match="not found"):
            await res_calendar(virtual_id)

    @pytest.mark.asyncio
    async def test_res_calendar_events_uses_calendar_scope(
        self, mock_client, sample_calendar, sample_event, calendar_id
    ):
        mock_client.list_events.return_value = [sample_event]
        virtual_cal_id = register_id(calendar_id)
        body = json.loads(await res_calendar_events(virtual_cal_id))
        assert body["count"] == 1
        # list_events called with the resolved real calendar_id
        call_kwargs = mock_client.list_events.call_args.kwargs
        assert call_kwargs["calendar_ids"] == [calendar_id]
        assert "window" in body
        # event line should contain the title and a virtual ID in brackets
        assert "Standup" in body["events"][0]
        assert "[" in body["events"][0] and "]" in body["events"][0]


# --- events window resources ---


class TestEventWindowResources:
    @pytest.mark.asyncio
    async def test_res_events_today_fans_out_per_account(
        self, mock_client, sample_calendar, sample_event
    ):
        mock_client.list_calendars.return_value = [sample_calendar]
        mock_client.list_events.return_value = [sample_event]
        body = json.loads(await res_events_today())
        assert body["count"] == 1
        assert body["window"]["start"].endswith("T00:00:00")
        # exactly one fan-out (one account)
        assert mock_client.list_events.await_count == 1

    @pytest.mark.asyncio
    async def test_res_events_this_week_window_is_seven_days(
        self, mock_client, sample_calendar
    ):
        mock_client.list_calendars.return_value = [sample_calendar]
        mock_client.list_events.return_value = []
        body = json.loads(await res_events_this_week())
        start = datetime.strptime(body["window"]["start"], _LOCAL_DT_FMT)
        end = datetime.strptime(body["window"]["end"], _LOCAL_DT_FMT)
        assert end - start == timedelta(days=7)
        assert start.weekday() == 0

    @pytest.mark.asyncio
    async def test_res_events_upcoming_handles_per_account_failure(
        self, mock_client, sample_calendar, sample_event
    ):
        # Two accounts, one fails: response should still include the surviving one
        other_calendar = Calendar(
            id=_make_calendar_id("a" * 24, "b@example.com"),
            account_id="a" * 24,
            integration_id="google",
            name="Other",
        )
        mock_client.list_calendars.return_value = [sample_calendar, other_calendar]

        async def list_events_side_effect(*, account_id, **_):
            if account_id == "a" * 24:
                raise RuntimeError("upstream sync error")
            return [sample_event]

        mock_client.list_events.side_effect = list_events_side_effect
        body = json.loads(await res_events_upcoming())
        assert body["count"] == 1  # only the surviving account contributed


# --- task resources ---


class TestTaskResources:
    @pytest.mark.asyncio
    async def test_res_tasks_filters_completed(self, mock_client):
        mock_client.list_tasks.return_value = [
            Task(id="t1", title="open A", progress="needs-action"),
            Task(id="t2", title="done", progress="completed"),
            Task(id="t3", title="open B", progress=None),
        ]
        body = json.loads(await res_tasks())
        assert body["count"] == 2
        assert body["filter"] == "open"
        titles = {t["title"] for t in body["tasks"]}
        assert titles == {"open A", "open B"}

    @pytest.mark.asyncio
    async def test_res_tasks_today_filters_by_due_date(self, mock_client):
        today_iso = datetime.now().replace(hour=12).strftime("%Y-%m-%dT%H:%M:%S")
        tomorrow_iso = (datetime.now() + timedelta(days=1)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        mock_client.list_tasks.return_value = [
            Task(id="t1", title="today", progress="needs-action", due=today_iso),
            Task(id="t2", title="tomorrow", progress="needs-action", due=tomorrow_iso),
            Task(id="t3", title="no due", progress="needs-action"),
            Task(id="t4", title="today done", progress="completed", due=today_iso),
        ]
        body = json.loads(await res_tasks_today())
        assert body["count"] == 1
        assert body["tasks"][0]["title"] == "today"
        assert body["filter"] == "open,due_today"


# --- tag resources ---


class TestTagResources:
    @pytest.mark.asyncio
    async def test_res_tags_returns_list(self, mock_client):
        mock_client.list_tags.return_value = [
            Tag(id="tag-uuid-1", name="errands", color="#abc"),
            Tag(id="tag-uuid-2", name="reading"),
        ]
        body = json.loads(await res_tags())
        assert body["count"] == 2
        assert {t["name"] for t in body["tags"]} == {"errands", "reading"}
