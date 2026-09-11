# MorgenMCP

An MCP server for the [Morgen](https://morgen.so) calendar API.

## Requirements

- [uv](https://docs.astral.sh/uv/) - [Install](https://docs.astral.sh/uv/getting-started/installation/) with `curl -LsSf https://astral.sh/uv/install.sh | sh`, `brew install uv`, or `winget install astral-sh.uv`
- [mise](https://mise.jdx.dev/) *(optional)* - [Install](https://mise.jdx.dev/getting-started.html) with `curl https://mise.run | sh`, `brew install mise`, or `winget install jdx.mise`. Convenient for local development: it puts the right Python on `PATH` in a plain shell and fails fast with setup instructions when `MORGEN_API_KEY` is unset. Everything works with uv alone — see [Environment Setup](#environment-setup).
- A Morgen API key - Get one from [Morgen Developer Portal](https://platform.morgen.so/developers-api)
- Python 3.12 or newer — Only needed when working from a clone (`uv` and `mise` provision this automatically from `.python-version`). End users running via `uvx` require no setup.

## Installation

No installation required — MCP clients run the server directly from GitHub.

Most clients use the same `mcpServers` JSON shape. Add this entry to your
client's MCP configuration:

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

The server speaks stdio, so no port or URL is involved. If your client asks for
a command rather than JSON, it is `uvx` with those arguments and
`MORGEN_API_KEY` in the environment. If it cannot find `uvx`, see
[Troubleshooting](#troubleshooting).

To pin to a specific version, replace `@main` with a version tag (e.g., `@v0.1.0`).

### Claude Desktop

The config file lives at `~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS, or `%APPDATA%\Claude\claude_desktop_config.json` on Windows. Paste the
block above, then restart Claude Desktop.

## Available Tools

Tools across accounts, calendars, events, tasks, and tags — read-only and mutating:

- **Accounts & calendars**: `list_accounts`, `list_calendars`, `update_calendar_metadata`
- **Events**: `list_events`, `create_event`, `update_event`, `delete_event`, `batch_update_events`, `batch_delete_events`
- **Tasks**: `list_tasks`, `list_task_lists`, `get_task`, `create_task`, `update_task`, `move_task`, `complete_task`, `reopen_task`, `delete_task`, `batch_delete_tasks`
- **Tags**: `list_tags`, `get_tag`, `create_tag`, `update_tag`, `delete_tag`

Pass `--read-only` (or set `MORGENMCP_READ_ONLY=1`) to expose only the read-only tools. For the exact live list with schemas and annotations, connect any MCP client or run the [MCP Inspector](#local-debugging-with-mcp-inspector).

### Compact event lines

`list_events` with `compact=true` (and every `morgen://events/*` resource)
returns one line per event instead of a JSON object, to save tokens:

```
Jul 23 08:00-11:00 CDT (America/Chicago): Deep work block {task} [oAxAjaC]
Jul 23 05:00-06:00 CDT (America/Chicago): Morning walk {routine} [c0HsnEl]
Jul 23 11:00-14:00 CDT (America/Chicago): Contractor visit {free} [suqNbDi]
Jul 23 14:00-14:30 CDT (America/Chicago): Dentist [l1_gFD6]
```

The optional `{kind}` tag before the ID tells a client what it is looking at:

| tag | meaning |
|---|---|
| `{task}` | Linked to a Morgen task — a flexible intention, usually movable. |
| `{routine}` | A [Morgen Routine](https://www.morgen.so/routines) occurrence: a recurring block you check off. |
| `{flexible}` | Morgen auto-scheduled this block, so it can be moved. |
| `{free}` | Does not mark you busy — informational, not an obligation. |
| *(no tag)* | An ordinary busy commitment. |

`{task}`, `{routine}` and `{flexible}` are mutually exclusive; `{free}` combines
with any of them as a comma-joined pair with no space, e.g. `{task,free}`.

Event titles may themselves contain `{}` or `[]`, so parse right to left: the
tag is the final `{...}` immediately preceding the trailing ` [id]`.

## Configuration

`MORGEN_API_KEY` is required; everything else is optional. Each setting has an
equivalent CLI flag, and the flag wins over the environment variable.

| Environment variable | CLI flag | Default | Description |
|---|---|---|---|
| `MORGEN_API_KEY` | — | *(required)* | Morgen API key. The server refuses to start without it. |
| `MORGENMCP_READ_ONLY` | `--read-only` | off | Truthy (`1`/`true`/`yes`/`on`) exposes only the read tools, disabling every mutating one. |
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
two endpoints differently: `/tasks/list` documents a default of 1 and a
maximum of 100, while `/tags/list` documents neither and returns all tags when
the parameter is omitted. A per-call `limit` argument on the tool always
overrides both the flag and the environment variable.

> **Note:** `MORGENMCP_TASKS_LIMIT` defaults to `100`, which is MorgenMCP's own
> choice rather than Morgen's. `/tasks/list` returns a *single* task when
> `limit` is omitted — its documented default is 1, and the API docs tell
> callers to always set the parameter explicitly, so the server never leaves it
> to Morgen. This is only a fallback: the tool asks the model to pass a `limit`
> suited to the request, and a per-call value always wins. Set this variable to
> bound what a model can pull in one call, not to express a typical page size.

## Troubleshooting

**`MORGEN_API_KEY is not set`** — the key goes in the `env` block of your MCP
client's server entry, not in a shell profile: the client launches the server
itself and does not inherit your terminal's environment. Get a key from the
[Morgen Developer Portal](https://platform.morgen.so/developers-api).

**`uvx: command not found`, or the server never starts** — desktop clients are
launched by the OS, not by your shell, so they see a minimal `PATH` that
usually excludes `~/.local/bin`, `/opt/homebrew/bin`, and version-manager
shims. Use an absolute path instead:

```bash
which uvx   # e.g. /opt/homebrew/bin/uvx
```

```json
"command": "/opt/homebrew/bin/uvx"
```

**Nothing appears in the client** — check the client's MCP log. Both failures
above surface there and nowhere else, because a stdio server's stderr goes to
the client, not to a terminal.

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

mise also puts the interpreter from `.python-version` on `PATH` in a plain shell, so a bare `python3` in a clone is the right one — useful because the source requires Python 3.12 or newer (see [Requirements](#requirements)).

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
