"""MCP resources exposing Morgen data for client-initiated reads.

Resources are read-only; writes still go through tools. URIs use the
`morgen://` scheme and are stable contract — renaming breaks any client
chats that have @-mentioned them.

URI scheme:
    morgen://server                       — server version & virtual-ID hash contract
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

import json
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from fastmcp.exceptions import ResourceError

from morgenmcp import __version__
from morgenmcp.client import get_client
from morgenmcp.models import Event
from morgenmcp.tools.calendars import _format_calendar
from morgenmcp.tools.events import (
    _fetch_events_by_account,
    _format_compact_event,
    _resolve_display_tz,
)
from morgenmcp.tools.id_registry import HASH_SPEC, register_id, resolve_id
from morgenmcp.tools.id_utils import extract_account_from_calendar
from morgenmcp.tools.outputs import ListTagsResult, fetch_coverage
from morgenmcp.tools.tags import _format_tag
from morgenmcp.tools.tasks import _format_task, _is_open
from morgenmcp.tools.utils import filter_none_values

_LOCAL_DT_FMT = "%Y-%m-%dT%H:%M:%S"


def _format_window(
    start_local: datetime, end_local: datetime
) -> tuple[tuple[str, str], tuple[str, str]]:
    """Return ((utc_start, utc_end), (local_start, local_end)) for a window."""
    utc_bounds = (
        start_local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    local_bounds = (
        start_local.strftime(_LOCAL_DT_FMT),
        end_local.strftime(_LOCAL_DT_FMT),
    )
    return utc_bounds, local_bounds


def _today_range(tz: tzinfo) -> tuple[tuple[str, str], tuple[str, str]]:
    """Local-midnight today → local-midnight tomorrow in ``tz``."""
    today = datetime.now(tz).date()
    start = datetime.combine(today, time.min, tzinfo=tz)
    end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)
    return _format_window(start, end)


def _this_week_range(tz: tzinfo) -> tuple[tuple[str, str], tuple[str, str]]:
    """ISO week: Monday 00:00 → next Monday 00:00 in ``tz``."""
    today = datetime.now(tz).date()
    monday = today - timedelta(days=today.weekday())
    start = datetime.combine(monday, time.min, tzinfo=tz)
    end = datetime.combine(monday + timedelta(days=7), time.min, tzinfo=tz)
    return _format_window(start, end)


def _upcoming_range(
    tz: tzinfo, days: int = 7
) -> tuple[tuple[str, str], tuple[str, str]]:
    """Now → now + N days in ``tz``."""
    start = datetime.now(tz).replace(microsecond=0)
    end = start + timedelta(days=days)
    return _format_window(start, end)


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
        by_account: dict[str, list[str]] = defaultdict(list)
        for cal_id in calendar_ids:
            by_account[extract_account_from_calendar(cal_id)].append(cal_id)
        if len(by_account) == 1:
            account_id, scoped_cal_ids = next(iter(by_account.items()))
            return await client.list_events(
                account_id=account_id,
                calendar_ids=scoped_cal_ids,
                start=start,
                end=end,
            )
        return await _fetch_events_by_account(client, by_account, start, end)

    calendars = await client.list_calendars()
    by_account = defaultdict(list)
    for cal in calendars:
        by_account[cal.account_id].append(cal.id)

    return await _fetch_events_by_account(client, by_account, start, end)


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


# --- Server resource ---


async def res_server() -> str:
    """Server metadata: version and the virtual-ID hash contract.

    Stable for the lifetime of HASH_SCHEME_VERSION. Consumers should
    snapshot HASH_SPEC['scheme_version'] alongside any persisted virtual
    ID; if the value changes between sessions, persisted IDs are stale
    and must be re-resolved by calling the relevant list_* tool.

    A downstream consumer can independently recompute virtual IDs from
    the published `reference_implementation` and verify them against the
    `test_vectors` entries — this is a self-describing contract.
    """
    return json.dumps(
        {
            "name": "morgen-calendar",
            "version": __version__,
            "virtualIdHash": HASH_SPEC,
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
    display_tz = _resolve_display_tz(None)
    utc_window, display_window = _upcoming_range(display_tz, days=7)
    events = await _fetch_events_in_window(*utc_window, calendar_ids=[real_id])
    return _events_payload(events, display_window, display_tz)


# --- Event window resources ---


async def res_events_today() -> str:
    """Events scheduled for today (local-midnight to local-midnight)."""
    display_tz = _resolve_display_tz(None)
    utc_window, display_window = _today_range(display_tz)
    events = await _fetch_events_in_window(*utc_window)
    return _events_payload(events, display_window, display_tz)


async def res_events_this_week() -> str:
    """Events scheduled this ISO week (Monday through Sunday, local)."""
    display_tz = _resolve_display_tz(None)
    utc_window, display_window = _this_week_range(display_tz)
    events = await _fetch_events_in_window(*utc_window)
    return _events_payload(events, display_window, display_tz)


async def res_events_upcoming() -> str:
    """Events from now through the next 7 days."""
    display_tz = _resolve_display_tz(None)
    utc_window, display_window = _upcoming_range(display_tz, days=7)
    events = await _fetch_events_in_window(*utc_window)
    return _events_payload(events, display_window, display_tz)


# --- Task resources ---


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
    result, fetch_limit = await client.list_tasks_and_spaces()
    open_tasks = [t for t in result.tasks if _is_open(t)]
    return json.dumps(
        {
            "tasks": [_format_task(t).model_dump(mode="json") for t in open_tasks],
            "count": len(open_tasks),
            "coverage": fetch_coverage(fetch_limit, len(result.tasks)),
            "filter": "open",
        }
    )


async def res_tasks_today() -> str:
    """Open tasks with a due date of today (local)."""
    client = get_client()
    result, fetch_limit = await client.list_tasks_and_spaces()
    today = date.today()
    todays = [t for t in result.tasks if _is_open(t) and _due_date(t) == today]
    return json.dumps(
        {
            "tasks": [_format_task(t).model_dump(mode="json") for t in todays],
            "count": len(todays),
            "coverage": fetch_coverage(fetch_limit, len(result.tasks)),
            "filter": "open,due_today",
            "date": today.isoformat(),
        }
    )


# --- Tag resources ---


async def res_tags() -> str:
    """List of user tags."""
    client = get_client()
    tags, fetch_limit = await client.list_tags()
    payload: ListTagsResult = {
        "tags": [_format_tag(t) for t in tags],
        "count": len(tags),
    }
    if fetch_limit is not None:
        payload["coverage"] = fetch_coverage(fetch_limit, len(tags))
    return json.dumps(payload)
