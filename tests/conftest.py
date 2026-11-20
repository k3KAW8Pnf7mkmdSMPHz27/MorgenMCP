"""Shared pytest fixtures and helpers."""

import os

import pytest

# Provide a fallback API key so tests that don't mock the client
# (e.g. MCP protocol tests exercising the lifespan) don't fail
# when direnv hasn't loaded .envrc into the shell.
os.environ.setdefault("MORGEN_API_KEY", "test-placeholder-key")

# Run the suite against FastMCP 4 WITHOUT the camelCase field-access shims
# (inputSchema, isError, ...). The shims are scheduled for removal in
# FastMCP 5; with this off, any camelCase read fails loudly in tests
# instead of warning silently.
os.environ.setdefault("FASTMCP_MCP_CAMELCASE_COMPAT", "false")


@pytest.fixture(autouse=True)
def _disable_persistent_store():
    """Prevent tests from writing to the real persistent store."""
    from morgenmcp.tools.id_registry import set_store

    set_store(None)
    yield
    set_store(None)
