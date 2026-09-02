# MorgenMCP

An MCP server for the [Morgen](https://morgen.so) calendar API.

## Requirements

- [uv](https://github.com/astral-sh/uv) - Install with `brew install uv`
- [mise](https://mise.jdx.dev/) *(optional)* - Install with `brew install mise`. Convenient for local development: it puts the right Python on `PATH` in a plain shell and fails fast with setup instructions when `MORGEN_API_KEY` is unset. Everything works with uv alone — see [Environment Setup](#environment-setup).
- A Morgen API key - Get one from [Morgen Developer Portal](https://platform.morgen.so/developers-api)
- Python 3.14 or newer — **only needed when working from a clone.** End users can skip this: `uvx` reads `requires-python` and provisions a suitable interpreter automatically. The source uses [PEP 758](https://peps.python.org/pep-0758/) syntax (unparenthesized `except A, B:`), which is a `SyntaxError` on 3.13 and earlier, so reaching for a system `python3` in a clone can fail confusingly. `mise install` (or `uv run`) gets you the right one — both read the exact version from `.python-version`.

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

## Configuration

`MORGEN_API_KEY` is required; everything else is optional. Each setting has an
equivalent CLI flag, and the flag wins over the environment variable.

| Environment variable | CLI flag | Default | Description |
|---|---|---|---|
| `MORGEN_API_KEY` | — | *(required)* | Morgen API key. The server refuses to start without it. |
| `MORGENMCP_READ_ONLY` | `--read-only` | off | Truthy (`1`/`true`/`yes`/`on`) exposes only the 6 read tools, disabling all 16 mutating ones. |
| `MORGENMCP_TASKS_LIMIT` | `--tasks-limit N` | `100` | Default `limit` sent to `/tasks/list`. Integer 1–100. |
| `MORGENMCP_TAGS_LIMIT` | `--tags-limit N` | *(unset)* | Default `limit` sent to `/tags/list`. Integer ≥ 1, no upper bound. Unset returns all tags. |
| `MORGENMCP_DISPLAY_TZ` | — | system local | IANA timezone (e.g. `America/Chicago`) for rendering compact event times. |
| `MORGENMCP_DATA_DIR` | — | platform data dir | Override the virtual-ID persistence directory. |

An invalid limit fails at startup with a clear error rather than silently
returning fewer results:

```bash
$ uv run morgenmcp --tasks-limit 500
morgenmcp: error: --tasks-limit must be <= 100 (got 500)
```

The two list limits are deliberately asymmetric, because Morgen documents the
two endpoints differently: `/tasks/list` documents a default of 100 and a
maximum of 100, while `/tags/list` documents neither and returns all tags when
the parameter is omitted. A per-call `limit` argument on the tool always
overrides both the flag and the environment variable.

> **Note:** `MORGENMCP_TASKS_LIMIT` defaults to `100` because Morgen's
> `/tasks/list` returns a *single* task when `limit` is omitted, despite
> documenting the default as 100. The server sends the documented value
> explicitly to compensate.

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

The server reads `MORGEN_API_KEY` from the process environment — it does not load a `.env` file itself. Either of the following supplies it. Both keep the key in a gitignored file; neither is required if the variable is already exported in your shell.

**With uv alone.** Put the key in a `.env` file (already gitignored) and let uv load it:

```bash
echo 'MORGEN_API_KEY=your_api_key' > .env
UV_ENV_FILE=.env uv run morgenmcp
```

Export `UV_ENV_FILE=.env` in your shell profile to skip the prefix. `uv run --env-file .env <cmd>` works the same way for one-off commands.

> If `uv` is itself installed *through* mise (a shim under `~/.local/share/mise/shims/uv`), every `uv` call routes through mise, and mise refuses to run against this repo's untrusted `mise.toml` — so `uv run` fails until you `mise trust`. That is a property of that install, not of this project; a standalone `uv` (`brew install uv`) is unaffected.

**With mise** *(optional, recommended if you already use it)*. This repo ships a `mise.toml` declaring `MORGEN_API_KEY` as required, so a missing key fails immediately with setup instructions instead of surfacing on the first tool call. `mise set` writes to a gitignored `mise.local.toml`, never the committed config:

```bash
mise trust
mise set --file mise.local.toml MORGEN_API_KEY=your_api_key
uv run morgenmcp
```

mise also puts the interpreter from `.python-version` on `PATH` in a plain shell, so a bare `python3` in a clone is the right one — useful because the source requires Python 3.14 (see [Requirements](#requirements)).

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

## Contributing

See [AGENTS.md](AGENTS.md) for environment setup, conventions, and the checks to
run before handing off changes.

**AI-assisted contributions are welcome and must be disclosed** — see
[AI_POLICY.md](AI_POLICY.md), adapted from the
[Ghostty project's AI policy](https://github.com/ghostty-org/ghostty/blob/main/AI_POLICY.md)
(MIT).

## License

Apache 2.0 - See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
