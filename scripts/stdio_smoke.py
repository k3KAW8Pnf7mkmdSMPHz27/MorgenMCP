"""Live stdio smoke for an installed server — no live API calls.

Runs against a clean install of the release wheel (placeholder API key,
throwaway data dir) and asserts the FastMCP 4 behaviors the in-memory
``Client(mcp)`` suite cannot see over a real stdio transport:

1. Modern (sessionless) connections actually NEGOTIATE the modern protocol
   (an assertion that fails against a pre-4 server, which would silently
   fall the client back to legacy), list tools, and read the static
   ``morgen://server`` resource.
2. Legacy connections complete the ``initialize`` handshake and report the
   MorgenMCP identity; raw JSON-RPC frames carry camelCase wire keys
   (``inputSchema``/``outputSchema``/``readOnlyHint``), proving SDK alias
   serialization end to end.
3. Every read from the child is deadline-bounded (a stalled server fails
   the step promptly instead of hanging CI), and the server shuts down
   cleanly when stdin closes.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

_EXPECTED_TOOLS = 24
# ISO date protocol revisions sort lexicographically.
_MODERN_PROTOCOL = "2026-07-28"
_PHASE_TIMEOUT = 90.0
_READ_TIMEOUT = 30.0


def _server_env() -> dict[str, str]:
    data_dir = tempfile.mkdtemp(prefix="morgenmcp-smoke-")
    return {
        **os.environ,
        "MORGEN_API_KEY": "smoke-...-key",
        "MORGENMCP_DATA_DIR": data_dir,
    }


async def _read_until_id(
    proc: asyncio.subprocess.Process, want_id: int, deadline: float
) -> dict:
    """Read line-delimited JSON-RPC until ``id == want_id``.

    The deadline is enforced by ``wait_for`` around the blocking readline
    itself: a wall-clock check between reads never runs while the child
    stalls mid-response (PR #57 review finding).
    """
    assert proc.stdout is not None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"no response to request id={want_id}")
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
        if not line:
            raise AssertionError("server closed stdout before responding")
        text = line.decode().strip()
        if not text:
            continue
        msg = json.loads(text)
        if msg.get("id") == want_id:
            return msg


async def _reap(proc: asyncio.subprocess.Process) -> None:
    """Close stdin and require a timely clean exit; kill+fail otherwise."""
    try:
        if proc.stdin is not None:
            proc.stdin.close()
    except Exception:
        pass
    try:
        rc = await asyncio.wait_for(proc.wait(), timeout=15)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise AssertionError(
            "server did not shut down cleanly on stdin close"
        ) from None
    assert rc == 0, f"exit code {rc}"


async def _raw_legacy_wire_check(exe: str) -> None:
    """Line-delimited JSON-RPC against a legacy-era client: camelCase wire."""
    proc = await asyncio.create_subprocess_exec(
        exe,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=_server_env(),
    )
    try:
        deadline = time.monotonic() + _READ_TIMEOUT

        async def send(msg: dict) -> None:
            assert proc.stdin is not None
            proc.stdin.write((json.dumps(msg, separators=(",", ":")) + "\n").encode())
            await asyncio.wait_for(proc.stdin.drain(), timeout=_READ_TIMEOUT)

        await send(
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
        init = await _read_until_id(proc, 1, deadline)
        assert init["result"]["serverInfo"]["name"] == "morgen-calendar", init[
            "result"
        ].get("serverInfo")
        await send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listing = await _read_until_id(proc, 2, deadline)
        tools = listing["result"]["tools"]
        assert len(tools) == _EXPECTED_TOOLS, len(tools)
        wire = json.dumps(tools)
        for key in ("inputSchema", "outputSchema", "readOnlyHint"):
            assert f'"{key}"' in wire, f"camelCase wire key {key!r} missing"
    finally:
        await _reap(proc)


async def _probe_mode(exe: str, mode: str) -> None:
    transport = StdioTransport(command=exe, args=[], env=_server_env())
    async with Client(transport, mode=mode) as client:  # type: ignore[arg-type]
        tools = await client.list_tools()
        assert len(tools) == _EXPECTED_TOOLS, (mode, len(tools))
        info = client.server_info
        assert info is not None and info.name == "morgen-calendar", (mode, info)
        if mode == "auto":
            # Without these assertions a pre-4 server passes by silently
            # negotiating the client back to legacy — observed when this
            # script ran against the 3.4.11 base revision (PR #57 review).
            version = client.protocol_version
            assert version is not None and version >= _MODERN_PROTOCOL, version
            assert client.initialize_result is None, "auto mode did a handshake"
        else:
            assert client.initialize_result is not None, "legacy skipped handshake"
        contents = await client.read_resource("morgen://server")
        assert contents, mode


async def main() -> None:
    exe = os.environ.get("SMOKE_SERVER")
    if not exe:
        sys.exit("SMOKE_SERVER must point at an installed morgenmcp launcher")
    for probe in (
        _probe_mode(exe, "auto"),
        _probe_mode(exe, "legacy"),
        _raw_legacy_wire_check(exe),
    ):
        await asyncio.wait_for(probe, timeout=_PHASE_TIMEOUT)
    print(
        "stdio smoke OK: sessionless path negotiated, legacy handshake + "
        "camelCase wire keys, deadline-bounded reads, clean shutdown"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (TimeoutError, AssertionError) as exc:
        sys.exit(f"stdio smoke FAILED: {exc}")
