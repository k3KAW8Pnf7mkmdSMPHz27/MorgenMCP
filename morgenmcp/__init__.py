"""MCP server for Morgen calendar API."""

from importlib.metadata import PackageNotFoundError, version

try:
    #: Resolved from the installed distribution, which uv-dynamic-versioning
    #: derives from the latest git tag at build time. Do not hardcode it —
    #: it is served to clients via `morgen://server` and MCP `serverInfo`,
    #: and a stale literal here silently misreports the running version.
    __version__ = version("morgenmcp")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
