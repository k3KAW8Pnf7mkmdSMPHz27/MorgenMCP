"""Live stdio smoke for an installed server — no live API calls.

Runs against a clean install of the release wheel (placeholder API key,
throwaway data dir) and asserts the FastMCP 4 behaviors the in-memory
``Client(mcp)`` suite cannot see over a real stdio transport:

1. Legacy connections complete the ``initialize`` handshake and report the
   MorgenMCP identity; raw JSON-RPC frames carry camelCase wire keys
   (``inputSchema``/``outputSchema``/``readOnlyHint``), proving SDK alias
   serialization end to end.
2. Modern (sessionless) connections list tools and read the static
   ``morgen://server`` resource.
3. The server shuts down cleanly when stdin closes.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

_EXPECTED_TOOLS = 24


def _server_env() -> dict[str, str]:
    data_dir = tempfile.mkdtemp(prefix="morgenmcp-smoke-")
    return {
        **os.environ,
        "MORGEN_API_KEY": "smoke-...-key",
        "MORGENMCP_DATA_DIR": data_dir,
    }


def _raw_legacy_wire_check(exe: str) -> None:
    """Line-delimited JSON-RPC against a legacy-era client: camelCase wire."""
    proc = subprocess.Popen(
        [exe],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=_server_env(),
        text=True,
    )
    assert proc.stdin is not None and proc.stdout is not None

    def send(msg: dict) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n")
        proc.stdin.flush()

    def recv_until_id(want_id: int, timeout: float = 30.0) -> dict:
        assert proc.stdout is not None
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                raise AssertionError("server closed stdout before responding")
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("id") == want_id:
                return msg
        raise AssertionError(f"no response to request id={want_id}")

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "stdio-smoke", "version": "0"},
                },
            }
        )
        init = recv_until_id(1)
        assert init["result"]["serverInfo"]["name"] == "morgen-calendar", init[
            "result"
        ].get("serverInfo")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listing = recv_until_id(2)
        tools = listing["result"]["tools"]
        assert len(tools) == _EXPECTED_TOOLS, len(tools)
        wire = json.dumps(tools)
        for key in ("inputSchema", "outputSchema", "readOnlyHint"):
            assert f'"{key}"' in wire, f"camelCase wire key {key!r} missing"
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise AssertionError(
                "server did not shut down cleanly on stdin close"
            ) from None
        assert proc.returncode == 0, f"exit code {proc.returncode}"


async def _fastmcp_client_modes(exe: str) -> None:
    for mode in ("auto", "legacy"):
        transport = StdioTransport(command=exe, args=[], env=_server_env())
        async with Client(transport, mode=mode) as client:  # type: ignore[arg-type]
            tools = await client.list_tools()
            assert len(tools) == _EXPECTED_TOOLS, (mode, len(tools))
            info = client.server_info
            assert info is not None and info.name == "morgen-calendar", mode
            contents = await client.read_resource("morgen://server")
            assert contents, mode


def main() -> None:
    exe = os.environ.get("SMOKE_SERVER")
    if not exe:
        sys.exit("SMOKE_SERVER must point at an installed morgenmcp launcher")
    asyncio.run(_fastmcp_client_modes(exe))
    _raw_legacy_wire_check(exe)
    print(
        "stdio smoke OK: legacy handshake + camelCase wire keys, "
        "modern sessionless path, clean shutdown"
    )


if __name__ == "__main__":
    main()
