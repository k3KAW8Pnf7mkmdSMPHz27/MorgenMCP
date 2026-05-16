"""MCP resources exposing Morgen data for client-initiated reads.

Resources are read-only; writes still go through tools. URIs use the
`morgen://` scheme and are stable contract — renaming breaks any client
chats that have @-mentioned them.

URI scheme:
    morgen://accounts                     — list of all accounts
    morgen://account/{account_id}         — one account
    morgen://calendars                    — list of all calendars
    morgen://calendar/{calendar_id}       — one calendar
    morgen://calendar/{calendar_id}/events — events in that calendar (today→+7d)
    morgen://events/today                 — today's events across all calendars
    morgen://events/this-week             — this week (Mon–Sun, ISO) across all
    morgen://events/upcoming              — next 7 days from now across all
    morgen://tasks                        — open tasks (not completed/cancelled)
    morgen://tasks/today                  — open tasks due today
    morgen://tags                         — list of tags

All bodies are JSON. IDs are virtual IDs, identical to those returned by tools.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo

from fastmcp.exceptions import ResourceError

from morgenmcp.client import get_client
from morgenmcp.models import Event
from morgenmcp.tools.calendars import _format_calendar
from morgenmcp.tools.events import _format_compact_event, _resolve_display_tz
from morgenmcp.tools.id_registry import register_id, resolve_id
from morgenmcp.tools.id_utils import extract_account_from_calendar
from morgenmcp.tools.tags import _format_tag
from morgenmcp.tools.tasks import _format_task
from morgenmcp.tools.utils import filter_none_values

_LOCAL_DT_FMT = "%Y-%m-%dT%H:%M:%S"


def _today_range() -> tuple[str, str]:
    """Local-midnight today → local-midnight tomorrow as LocalDateTime strings."""
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.strftime(_LOCAL_DT_FMT), end.strftime(_LOCAL_DT_FMT)


def _this_week_range() -> tuple[str, str]:
    """ISO week: Monday 00:00 → next Monday 00:00 (local time)."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    next_monday = monday + timedelta(days=7)
    return monday.strftime(_LOCAL_DT_FMT), next_monday.strftime(_LOCAL_DT_FMT)


def _upcoming_range(days: int = 7) -> tuple[str, str]:
    """Now → now + N days, both as LocalDateTime."""
    start = datetime.now().replace(microsecond=0)
    end = start + timedelta(days=days)
    return start.strftime(_LOCAL_DT_FMT), end.strftime(_LOCAL_DT_FMT)


async def _fetch_events_in_window(
    start: str,
    end: str,
    calendar_ids: list[str] | None = None,
) -> list[Event]:
    """Fetch events in a window across one or all calendars.

    Mirrors the tool-side parallel-by-account fetch but without progress
    reporting (resources have no per-call ctx for that).
    """
    client = get_client()

    if calendar_ids is not None:
        if not calendar_ids:
            return []
        account_id = extract_account_from_calendar(calendar_ids[0])
        return await client.list_events(
            account_id=account_id,
            calendar_ids=calendar_ids,
            start=start,
            end=end,
        )

    calendars = await client.list_calendars()
    by_account: dict[str, list[str]] = defaultdict(list)
    for cal in calendars:
        by_account[cal.account_id].append(cal.id)

    async def fetch(acc_id: str, cal_ids: list[str]) -> list[Event]:
        return await client.list_events(
            account_id=acc_id,
            calendar_ids=cal_ids,
            start=start,
            end=end,
        )

    results = await asyncio.gather(
        *(fetch(a, c) for a, c in by_account.items()),
        return_exceptions=True,
    )
    out: list[Event] = []
    for r in results:
        if isinstance(r, BaseException):
            continue  # silently skip per-account failures, same as tool
        out.extend(r)
    return out


def _format_account(acc) -> dict:
    return filter_none_values(
        {
            "id": register_id(acc.id),
            "integrationId": acc.integration_id,
            "email": acc.provider_user_id,
            "displayName": acc.provider_user_display_name,
        }
    )


def _events_payload(
    events: list[Event], window: tuple[str, str], display_tz: tzinfo
) -> str:
    return json.dumps(
        {
            "events": [_format_compact_event(e, display_tz) for e in events],
            "count": len(events),
            "window": {"start": window[0], "end": window[1]},
        }
    )


# --- Account resources ---


async def res_accounts() -> str:
    """List of connected calendar accounts."""
    client = get_client()
    accounts = await client.list_accounts()
    return json.dumps(
        {
            "accounts": [_format_account(a) for a in accounts],
            "count": len(accounts),
        }
    )


async def res_account(account_id: str) -> str:
    """Single account by virtual ID."""
    real_id = resolve_id(account_id)
    client = get_client()
    accounts = await client.list_accounts()
    for acc in accounts:
        if acc.id == real_id:
            return json.dumps({"account": _format_account(acc)})
    raise ResourceError(f"Account {account_id!r} not found")


# --- Calendar resources ---


async def res_calendars() -> str:
    """List of all calendars across all accounts."""
    client = get_client()
    calendars = await client.list_calendars()
    return json.dumps(
        {
            "calendars": [_format_calendar(c) for c in calendars],
            "count": len(calendars),
        }
    )


async def res_calendar(calendar_id: str) -> str:
    """Single calendar by virtual ID."""
    real_id = resolve_id(calendar_id)
    client = get_client()
    calendars = await client.list_calendars()
    for cal in calendars:
        if cal.id == real_id:
            return json.dumps({"calendar": _format_calendar(cal)})
    raise ResourceError(f"Calendar {calendar_id!r} not found")


async def res_calendar_events(calendar_id: str) -> str:
    """Events in a single calendar from today through next 7 days."""
    real_id = resolve_id(calendar_id)
    start, end = _upcoming_range(days=7)
    events = await _fetch_events_in_window(start, end, calendar_ids=[real_id])
    display_tz = _resolve_display_tz(None)
    return _events_payload(events, (start, end), display_tz)


# --- Event window resources ---


async def res_events_today() -> str:
    """Events scheduled for today (local-midnight to local-midnight)."""
    start, end = _today_range()
    events = await _fetch_events_in_window(start, end)
    display_tz = _resolve_display_tz(None)
    return _events_payload(events, (start, end), display_tz)


async def res_events_this_week() -> str:
    """Events scheduled this ISO week (Monday through Sunday, local)."""
    start, end = _this_week_range()
    events = await _fetch_events_in_window(start, end)
    display_tz = _resolve_display_tz(None)
    return _events_payload(events, (start, end), display_tz)


async def res_events_upcoming() -> str:
    """Events from now through the next 7 days."""
    start, end = _upcoming_range(days=7)
    events = await _fetch_events_in_window(start, end)
    display_tz = _resolve_display_tz(None)
    return _events_payload(events, (start, end), display_tz)


# --- Task resources ---

_OPEN_PROGRESS_VALUES = {"needs-action", "in-process", None}


def _is_open(task) -> bool:
    return task.progress in _OPEN_PROGRESS_VALUES


def _due_date(task) -> date | None:
    if not task.due:
        return None
    try:
        return datetime.fromisoformat(task.due).date()
    except ValueError:
        return None


async def res_tasks() -> str:
    """Open tasks (not completed or cancelled)."""
    client = get_client()
    tasks = await client.list_tasks()
    open_tasks = [t for t in tasks if _is_open(t)]
    return json.dumps(
        {
            "tasks": [_format_task(t) for t in open_tasks],
            "count": len(open_tasks),
            "filter": "open",
        }
    )


async def res_tasks_today() -> str:
    """Open tasks with a due date of today (local)."""
    client = get_client()
    tasks = await client.list_tasks()
    today = date.today()
    todays = [t for t in tasks if _is_open(t) and _due_date(t) == today]
    return json.dumps(
        {
            "tasks": [_format_task(t) for t in todays],
            "count": len(todays),
            "filter": "open,due_today",
            "date": today.isoformat(),
        }
    )


# --- Tag resources ---


async def res_tags() -> str:
    """List of user tags."""
    client = get_client()
    tags = await client.list_tags()
    return json.dumps(
        {
            "tags": [_format_tag(t) for t in tags],
            "count": len(tags),
        }
    )
