# MorgenMCP

An MCP server for the [Morgen](https://morgen.so) calendar API.

## Requirements

- [uv](https://github.com/astral-sh/uv) - Install with `brew install uv`
- [mise](https://mise.jdx.dev/) - Install with `brew install mise` (used to manage the `MORGEN_API_KEY` environment variable during local development)
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

22 tools across accounts, calendars, events, tasks, and tags — 6 read-only, 16 mutating:

- **Accounts & calendars**: `list_accounts`, `list_calendars`, `update_calendar_metadata`
- **Events**: `list_events`, `create_event`, `update_event`, `delete_event`, `batch_update_events`, `batch_delete_events`
- **Tasks**: `list_tasks`, `get_task`, `create_task`, `update_task`, `move_task`, `complete_task`, `reopen_task`, `delete_task`, `batch_delete_tasks`
- **Tags**: `list_tags`, `create_tag`, `update_tag`, `delete_tag`

Pass `--read-only` (or set `MORGENMCP_READ_ONLY=1`) to expose only the 6 read-only tools. For the exact live list with schemas and annotations, connect any MCP client or run the [MCP Inspector](#local-debugging-with-mcp-inspector).

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

The server reads `MORGEN_API_KEY` from the process environment — it does not load a `.env` file itself. This repo ships a `mise.toml` that declares `MORGEN_API_KEY` as required; set the actual value via [mise](https://mise.jdx.dev/), which writes it to a gitignored `mise.local.toml` rather than the committed config:

```bash
mise trust
mise set --file mise.local.toml MORGEN_API_KEY=your_api_key
```

Then run the server:

```bash
uv run morgenmcp
```

### Local Debugging with MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) provides a web UI for testing tools and inspecting requests/responses:

```bash
npx @modelcontextprotocol/inspector uv run morgenmcp
```

Opens at http://localhost:6274

## Releasing

Releases are managed via git tags:

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

Users can then reference the specific version in their MCP client configuration.

## License

Apache 2.0 - See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
