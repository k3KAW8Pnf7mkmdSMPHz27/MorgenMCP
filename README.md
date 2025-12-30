# MorgenMCP

An MCP server for the [Morgen](https://morgen.so) calendar API.

## Requirements

- [uv](https://github.com/astral-sh/uv) - Install with `brew install uv`
- A Morgen API key - Get one from [Morgen Developer Portal](https://platform.morgen.so/developers-api)

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

# Run tests
uv run pytest
```

### Environment Setup

Run the setup script to configure your development environment:

```bash
uv run setup-dev
```

This script will:
1. Check that [direnv](https://direnv.net/) is installed (with instructions if not)
2. Prompt for your Morgen API key
3. Create a `.envrc` file with your key
4. Enable direnv for this directory

Once complete, your API key will be automatically available whenever you're in the project directory:

```bash
# Run the server locally
uv run morgenmcp
```

### Local Debugging with MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) is a developer tool for testing and debugging MCP servers. It provides a web-based UI to interact with your server, test tools, and inspect requests/responses.

```bash
# Run the inspector with the local server
npx @modelcontextprotocol/inspector -e MORGEN_API_KEY=$MORGEN_API_KEY uv run morgenmcp
```

This starts:
- **Inspector UI** at `http://localhost:6274` - Interactive interface for testing tools
- **MCP Proxy** at `http://localhost:6277` - Bridges the web UI to the MCP server

From the Inspector UI, you can:
- List and test all available tools (list_calendars, create_event, etc.)
- View request/response payloads
- Debug tool execution in real-time

## Releasing

Releases are managed via git tags:

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Users can then reference the specific version in their MCP client configuration.

## License

Apache 2.0 - See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
