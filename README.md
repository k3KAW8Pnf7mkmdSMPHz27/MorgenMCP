# MorgenMCP

An MCP server for the [Morgen](https://morgen.so) calendar API.

## Requirements

- [uv](https://github.com/astral-sh/uv) - Install with `brew install uv`
- A Morgen API key - Get one from [Morgen Settings](https://platform.morgen.so/settings/api-keys)

## Installation

No installation required! MCP clients run the server directly from GitHub.

### Claude Desktop

Add to your Claude Desktop configuration (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "morgen": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/k3KAW8Pnf7mkmdSMPHz27/MorgenMCP@main",
        "morgenmcp"
      ],
      "env": {
        "MORGEN_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

To pin to a specific version, replace `@main` with a version tag (e.g., `@v0.1.0`).

## Available Tools

- **list_calendars** - List all calendars
- **update_calendar_metadata** - Update calendar display name or color
- **list_events** - List events with optional date filtering
- **create_event** - Create a new calendar event
- **update_event** - Update an existing event
- **delete_event** - Delete an event

## Development

```bash
# Clone the repository
git clone https://github.com/k3KAW8Pnf7mkmdSMPHz27/MorgenMCP.git
cd MorgenMCP

# Install dependencies
uv sync --all-extras

# Set your API key
export MORGEN_API_KEY="your_api_key"

# Run the server locally
uv run morgenmcp

# Run tests
uv run pytest
```

## Releasing

Releases are managed via git tags:

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Users can then reference the specific version in their MCP client configuration.

## License

Apache 2.0 - See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
