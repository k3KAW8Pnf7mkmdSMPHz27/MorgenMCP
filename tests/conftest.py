"""Shared pytest fixtures and helpers."""

import os

# Provide a fallback API key so tests that don't mock the client
# (e.g. MCP protocol tests exercising the lifespan) don't fail
# when direnv hasn't loaded .envrc into the shell.
os.environ.setdefault("MORGEN_API_KEY", "test-placeholder-key")
