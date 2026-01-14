"""MCP tools for Morgen account operations."""

from morgenmcp.client import get_client
from morgenmcp.tools.id_registry import register_id
from morgenmcp.tools.utils import filter_none_values, handle_tool_errors


@handle_tool_errors
async def list_accounts() -> dict:
    """List all connected calendar accounts.

    Returns a list of accounts with their IDs, integration types, and user info.
    Use this to discover available accounts before performing calendar operations.

    Returns:
        Dictionary with 'accounts' key containing list of account objects.
    """
    client = get_client()
    accounts = await client.list_accounts()

    return {
        "accounts": [
            filter_none_values({
                "id": register_id(acc.id),
                "integrationId": acc.integration_id,
                "email": acc.provider_user_id,
                "displayName": acc.provider_user_display_name,
            })
            for acc in accounts
        ],
        "count": len(accounts),
    }
