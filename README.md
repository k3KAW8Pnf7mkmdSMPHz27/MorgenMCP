# MorgenMCP

[![PyPI version](https://img.shields.io/pypi/v/morgenmcp)](https://pypi.org/project/morgenmcp/)

An unofficial MCP server for the [Morgen](https://morgen.so) calendar API.

> [!NOTE]
> This is an independent, community-maintained project and is not affiliated with, endorsed by, or sponsored by Morgen AG. Morgen is a trademark of Morgen AG.

## Installation

Run MorgenMCP locally from [PyPI](https://pypi.org/project/morgenmcp/), without
cloning this repository.

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/):
   `brew install uv` on macOS, or `winget install astral-sh.uv` on Windows.
   For Linux and other installation methods, follow the uv link.
2. Get an API key from the [Morgen Developer Portal](https://platform.morgen.so/developers-api).
3. Choose your client below. uv manages the required Python version (3.12 or newer).

| Client | Setup |
|---|---|
| Claude Desktop | [Configuration file](#claude-desktop) |
| Claude Code | [CLI command](#claude-code) |
| Cursor | [Install button and configuration](#cursor) |
| VS Code | [Install button and configuration](#vs-code) |
| Other MCP clients | [Generic stdio configuration](#other-mcp-clients) |

The server uses stdio: your client starts `uvx morgenmcp`; no server URL or
port is needed. If it cannot find `uvx`, use its absolute path as described in
[Troubleshooting](#troubleshooting).

### Claude Desktop

Open **Settings → Developer → Edit Config**. The file is
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS,
or `%APPDATA%\Claude\claude_desktop_config.json` on Windows.

Merge the [generic configuration](#other-mcp-clients) into the file, replace
`your_api_key_here` with your key, and restart Claude Desktop. Preserve any
other servers already configured. Then [verify the connection](#verify-the-connection).

### Claude Code

Replace the placeholder and run this command in your terminal:

```sh
claude mcp add --scope user --env MORGEN_API_KEY=your_api_key_here --transport stdio morgen -- uvx morgenmcp
```

This adds MorgenMCP to your personal configuration across projects. The key is
stored in that configuration; entering it literally can also leave it in shell
history. Use your shell's private-input mechanism if needed. In Claude Code,
run `/mcp` to check the server status, then
[verify the connection](#verify-the-connection).

See the [Claude Code MCP guide](https://code.claude.com/docs/en/mcp) for scopes
and environment-variable configuration.

### Cursor

[![Install in Cursor](https://img.shields.io/badge/Install_in-Cursor-black)](https://cursor.com/en/install-mcp?name=morgen&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJtb3JnZW5tY3AiXSwiZW52Ijp7Ik1PUkdFTl9BUElfS0VZIjoieW91cl9hcGlfa2V5X2hlcmUifX0%3D)

The button opens Cursor with a proposed local server configuration. Replace
`your_api_key_here` in the server's `env` configuration with your Morgen key
before using it. The button contains only a placeholder; never put a real key
in a shared install link.

For manual setup, open **Cursor Settings → Tools & MCP**, or edit your personal
`~/.cursor/mcp.json`. Merge the [generic configuration](#other-mcp-clients),
replace the key placeholder, and enable the server. Keep credentials in your
personal configuration rather than a committed project file. Then
[verify the connection](#verify-the-connection).

See [Cursor's MCP documentation](https://cursor.com/docs/mcp) and
[install-link format](https://cursor.com/docs/mcp/install-links).

### VS Code

[![Install in VS Code](https://img.shields.io/badge/Install_in-VS_Code-007ACC)](https://vscode.dev/redirect/mcp/install?%7B%22name%22%3A%22morgen%22%2C%22type%22%3A%22stdio%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22morgenmcp%22%5D%2C%22env%22%3A%7B%22MORGEN_API_KEY%22%3A%22%24%7Binput%3Amorgen-api-key%7D%22%7D%2C%22inputs%22%3A%5B%7B%22type%22%3A%22promptString%22%2C%22id%22%3A%22morgen-api-key%22%2C%22description%22%3A%22Morgen%20API%20key%22%2C%22password%22%3Atrue%7D%5D%7D)

The button opens VS Code's installation flow with a password input for your
Morgen API key. Review the configuration and install it in your user profile.
If the browser does not open the app, use the manual setup below.

Run **MCP: Open User Configuration** from the Command Palette and merge this
configuration, preserving any existing servers and inputs:

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "morgen-api-key",
      "description": "Morgen API key",
      "password": true
    }
  ],
  "servers": {
    "morgen": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "morgenmcp"
      ],
      "env": {
        "MORGEN_API_KEY": "${input:morgen-api-key}"
      }
    }
  }
}
```

Start `morgen` from the MCP configuration editor and enter your key when
prompted. Then [verify the connection](#verify-the-connection).

These input prompts are supported in VS Code's Local harness; servers requiring
interactive inputs are not forwarded to Copilot harness sessions. See the
[VS Code configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)
for supported credential options in your session.

### Other MCP clients

Merge this into your client's MCP configuration and replace the key placeholder:

```json
{
  "mcpServers": {
    "morgen": {
      "command": "uvx",
      "args": [
        "morgenmcp"
      ],
      "env": {
        "MORGEN_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

If your client asks for separate fields, use command `uvx`, arguments
`morgenmcp`, and environment variable `MORGEN_API_KEY`. Follow your client's
configuration format; not every client uses the `mcpServers` wrapper.

### Verify the connection

Ask your assistant: **“List my Morgen calendars.”** Check that it invokes
`list_accounts` and/or `list_calendars` and returns your calendars. You can
also try **“What is on my Morgen calendar today?”**

If startup fails or the tools do not appear, see [Troubleshooting](#troubleshooting).

### Read-only mode and version pinning

To expose only read tools, change `args` to
`["morgenmcp", "--read-only"]`. For the Claude Code command, append
`--read-only` after `uvx morgenmcp`.

To pin a release, use `["morgenmcp==0.2.1"]` (replace the version with your
chosen release). To run an unreleased commit, use
`["--from", "git+https://github.com/k3KAW8Pnf7mkmdSMPHz27/MorgenMCP@main", "morgenmcp"]`.

## Available Tools

Tools across accounts, calendars, events, tasks, and tags — read-only and mutating:

- **Accounts & calendars**: `list_accounts`, `list_calendars`, `update_calendar_metadata`
- **Events**: `list_events`, `create_event`, `update_event`, `delete_event`, `batch_update_events`, `batch_delete_events`
- **Tasks**: `list_tasks`, `list_task_lists`, `get_task`, `create_task`, `update_task`, `move_task`, `complete_task`, `reopen_task`, `delete_task`, `batch_delete_tasks`
- **Tags**: `list_tags`, `get_tag`, `create_tag`, `update_tag`, `delete_tag`

Pass `--read-only` (or set `MORGENMCP_READ_ONLY=1`) to expose only the read-only tools. For the exact live list with schemas and annotations, connect any MCP client or run the [MCP Inspector](#local-debugging-with-mcp-inspector).

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

**`MORGEN_API_KEY is not set`** — provide the key through your client's setup
above: the `env` block, VS Code password prompt, or Claude Code configuration.
Desktop clients may not inherit your terminal's environment. Get a key from the
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

Use Python 3.12 or newer. uv provisions the version pinned in
`.python-version` for this checkout. [mise](https://mise.jdx.dev/) is optional;
see [Environment Setup](#environment-setup) if you already use it.

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

mise also puts the interpreter from `.python-version` on `PATH` in a plain shell, so a bare `python3` in a clone is the right one — useful because the source requires Python 3.12 or newer (see [Development](#development)).

### Local Debugging with MCP Inspector

The [MCP Inspector](https://github.com/modelcontextprotocol/inspector) provides a web UI for testing tools and inspecting requests/responses:

```bash
npx @modelcontextprotocol/inspector uv run morgenmcp
```

Opens at http://localhost:6274

## Releasing

Releases are managed via git tags:

```bash
git tag -a v0.2.1 -m "Release v0.2.1"
git push origin v0.2.1
```

Stable `vX.Y.Z` tags trigger the GitHub Actions release workflow, which runs
tests, builds wheel and sdist distributions and a desktop bundle, and requires
verified Sigstore provenance for every release artifact before publishing to
PyPI and GitHub Releases. The workflow uses the existing `pypi` environment
and PyPI trusted publishing. Verified files are retained as an Actions artifact
for 30 days if publication needs recovery.

### Verify a release download

Release assets include `provenance.sigstore.json` and `SHA256SUMS`. With a recent
[GitHub CLI](https://cli.github.com/), replace `vX.Y.Z` below with your release:

```sh
REPO=k3KAW8Pnf7mkmdSMPHz27/MorgenMCP
TAG=vX.Y.Z
COMMIT="$(gh api "repos/$REPO/commits/$TAG" --jq .sha)"
gh release download "$TAG" --repo "$REPO" --dir release-download \
  --pattern '*.mcpb' --pattern provenance.sigstore.json

gh attestation verify "release-download/morgenmcp-${TAG#v}.mcpb" \
  --bundle release-download/provenance.sigstore.json \
  --repo "$REPO" --signer-workflow "$REPO/.github/workflows/release.yml" \
  --source-ref "refs/tags/$TAG" --source-digest "$COMMIT" \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  --predicate-type https://slsa.dev/provenance/v1 --deny-self-hosted-runners
```

Proceed only if verification succeeds. Use a separately reviewed commit SHA
for `COMMIT` if you want to pin it independently of the current GitHub tag.
The same command can verify a downloaded wheel, source archive, or checksums file.
Sigstore verifies build provenance; it does not confer Anthropic-verified
publisher status in Claude Desktop. The manual `provenance-trial.yml` workflow
exercises signing, verification, and tamper rejection without publishing a release.

## Contributing

See [AGENTS.md](AGENTS.md) for environment setup, conventions, and the checks to
run before handing off changes.

**AI-assisted contributions are welcome and must be disclosed** — see
[AI_POLICY.md](AI_POLICY.md), adapted from the
[Ghostty project's AI policy](https://github.com/ghostty-org/ghostty/blob/main/AI_POLICY.md)
(MIT).

## License

Apache 2.0 - See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.
