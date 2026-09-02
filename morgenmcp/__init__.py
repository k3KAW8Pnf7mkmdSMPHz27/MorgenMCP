"""MCP server for Morgen calendar API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("morgenmcp")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
