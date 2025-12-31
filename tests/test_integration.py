"""Integration tests that hit the real Morgen API.

Run with: uv run pytest tests/test_integration.py -v -s
Requires MORGEN_API_KEY in .env or environment.
"""

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.integration


@pytest.fixture
def api_key():
    """Get API key or skip test."""
    key = os.environ.get("MORGEN_API_KEY")
    if not key:
        pytest.skip("MORGEN_API_KEY not set")
    return key


@pytest.mark.asyncio
async def test_list_calendars_live(api_key):
    """Test list_calendars against real API and print response."""
    from morgenmcp.client import MorgenClient

    async with MorgenClient(api_key=api_key) as client:
        calendars = await client.list_calendars()

    print(f"\n=== Found {len(calendars)} calendars ===")
    for cal in calendars:
        print(f"  - {cal.name} (id={cal.id}, account={cal.account_id})")

    assert len(calendars) >= 0  # Just verify it returns a list


@pytest.mark.asyncio
async def test_list_events_live(api_key):
    """Test list_events against real API and print response."""
    from datetime import datetime, timedelta

    from morgenmcp.client import MorgenClient

    async with MorgenClient(api_key=api_key) as client:
        calendars = await client.list_calendars()
        if not calendars:
            pytest.skip("No calendars available")

        # Get events for the next 7 days from first calendar
        cal = calendars[0]
        start = datetime.now().strftime("%Y-%m-%dT00:00:00Z")
        end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59Z")

        events = await client.list_events(
            account_id=cal.account_id,
            calendar_ids=[cal.id],
            start=start,
            end=end,
        )

    print(f"\n=== Found {len(events)} events in '{cal.name}' ===")
    for evt in events[:5]:  # Show first 5
        print(f"  - {evt.title} ({evt.start})")

    assert len(events) >= 0


@pytest.mark.asyncio
async def test_create_event_response_format(api_key):
    """Test create_event response format (creates then immediately deletes)."""
    from morgenmcp.client import MorgenClient
    from morgenmcp.models import EventCreateRequest, EventDeleteRequest

    async with MorgenClient(api_key=api_key) as client:
        calendars = await client.list_calendars()
        writable = [c for c in calendars if c.my_rights and c.my_rights.may_write_all]
        if not writable:
            pytest.skip("No writable calendars available")

        cal = writable[0]

        # Create a test event
        request = EventCreateRequest(
            account_id=cal.account_id,
            calendar_id=cal.id,
            title="[TEST] MorgenMCP Integration Test - DELETE ME",
            start="2099-12-31T10:00:00",
            duration="PT30M",
            time_zone="UTC",
            show_without_time=False,
        )

        response = await client.create_event(request)
        print("\n=== Create Event Response ===")
        print(f"  event.id: {response.event.id}")
        print(f"  event.calendar_id: {response.event.calendar_id}")
        print(f"  event.account_id: {response.event.account_id}")

        # Immediately delete the test event
        delete_request = EventDeleteRequest(
            id=response.event.id,
            account_id=cal.account_id,
            calendar_id=cal.id,
        )
        await client.delete_event(delete_request)
        print("  (test event deleted)")

        assert response.event.id is not None
