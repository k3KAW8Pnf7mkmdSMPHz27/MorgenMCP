# MorgenMCP Contributor Guide

## Project overview

MorgenMCP is a Python MCP server that exposes the Morgen calendar, task, and
tag APIs through FastMCP. The package source is in `morgenmcp/`; tests are in
`tests/`.

## Environment and commands

- Use Python 3.14 or newer and manage dependencies with `uv`. The floor is
  real, not nominal: the source uses PEP 758 syntax (unparenthesized
  `except A, B:`), which is a `SyntaxError` on 3.13 and earlier. `uv` and
  `mise` both provision a correct interpreter; a bare system `python3` may
  not be one.
- The exact interpreter lives in **`.python-version`** and nowhere else.
  `uv` reads it natively; `mise.toml` opts in via
  `idiomatic_version_file_enable_tools`. Bump that one file to change the
  version — do not add a `[tools] python` pin to `mise.toml`, which would
  override it.
- Install development dependencies with `uv sync --all-extras`.
- Set up git hooks once with `pre-commit install`.
- Run the default test suite with `uv run pytest`. Integration tests are
  excluded by default; run them explicitly with `uv run pytest -m integration`
  only when `MORGEN_API_KEY` is configured and real API calls are intended.
- Before handing off Python changes, run:
  - `uv run ruff check .`
  - `uv run ruff format .`
  - `uv run pyright morgenmcp/`
  - relevant tests (or the full non-integration suite when practical)

## Code conventions

- Follow the existing async style for API, tool, and resource code.
- Keep user-facing MCP inputs and outputs validated with the existing Pydantic
  models and validator helpers.
- Preserve virtual-ID behavior in `morgenmcp/tools/id_registry.py`; callers
  should not expose raw Morgen IDs.
- Do not log API keys, raw IDs that can reveal account information, or other
  secrets. Keep persistent ID storage owner-only.
- Add or update focused tests alongside behavior changes. Mock HTTP requests
  with the existing `respx` patterns; do not let normal tests call the live API.

## Scope and safety

- Do not modify generated lockfiles or dependency versions unless the task
  requires it.
- Preserve public MCP tool names and parameter compatibility unless a breaking
  change is explicitly requested.
- Keep `.env` and credentials local; never add them to version control.

## AI usage

- Read and follow [AI_POLICY.md](AI_POLICY.md).
- Disclose all AI assistance in the PR description (tool and extent).
- Mark AI-assisted commits with `Assisted-by: LLM (<tool>, <model>)`; do not use `Co-Authored-By`.
- Verify claims against this repository (run the command, check output) before reporting.
- Ensure a human understands and can explain all submitted changes.

## Working alongside other agents

Multiple agents or harnesses may work on this repo at the same time, each in
its own branch or worktree off `main`. `morgenmcp/client.py`,
`morgenmcp/server.py`, and `morgenmcp/tools/outputs.py` are touched by nearly
every tool-adding change and are the most likely files to conflict between
concurrent branches — this has already happened in practice (two same-day PRs
both rewrote `MorgenClient.list_tasks`). Before opening a PR:

- Rebase onto the latest `main`.
- Skim the other open PRs' file lists for overlap with files you changed; note
  any expected conflict and how to resolve it (which side's fix must survive)
  directly in your PR description.
- If your change duplicates work already proposed in another open PR, say so
  rather than leaving it for a reviewer to discover.
