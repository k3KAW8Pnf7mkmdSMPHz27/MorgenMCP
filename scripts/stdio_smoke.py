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


async def _reap(proc: asyncio.subprocess.Process, *, strict: bool) -> None:
    """Close stdin, exit promptly (escalating to kill), drain stdout, report.

    stdout must be drained before the loop closes: the subprocess
    transport's pipe feed pauses once the stream buffer limit is exceeded,
    so ``wait()`` can hang forever on a child that wrote a large line
    (PR #57 review finding). Grace is short and a lingering child is
    KILLED rather than poll-waited — measured locally, draining a
    still-alive writer took ~75 s, while kill+drain is a few seconds.

    ``strict`` must be False when reap runs while another exception is in
    flight: teardown failures then stay silent so the original error
    survives. sys.exc_info() is deliberately NOT used — a bare finally
    does not establish handled-exception state, so the caller must say.
    """
    try:
        if proc.stdin is not None:
            proc.stdin.close()
    except Exception:
        pass

    rc: int | None = None
    teardown_error: Exception | None = None
    try:
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError:
            proc.kill()
            rc = await asyncio.wait_for(proc.wait(), timeout=10)
        if proc.stdout is not None:
            # Child is gone; drain buffered stdout to EOF (bounded).
            while True:
                chunk = await asyncio.wait_for(proc.stdout.read(65536), timeout=10)
                if not chunk:
                    break
    except (TimeoutError, OSError) as exc:  # teardown itself wedged
        teardown_error = exc

    if not strict:
        return
    if teardown_error is not None:
        raise AssertionError(f"server did not shut down cleanly: {teardown_error}")
    if rc != 0:
        raise AssertionError(f"exit code {rc}")


async def _raw_legacy_wire_check(exe: str) -> None:
    """Line-delimited JSON-RPC against a legacy-era client: camelCase wire."""
    proc = await asyncio.create_subprocess_exec(
        exe,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=_server_env(),
    )
    failed = True
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
        failed = False
    finally:
        await _reap(proc, strict=not failed)


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
    # Callables, not coroutine objects: eagerly created coroutines emit
    # "never awaited" RuntimeWarnings for the probes a failure skips.
    phases = (
        ("auto client", lambda: _probe_mode(exe, "auto")),
        ("legacy client", lambda: _probe_mode(exe, "legacy")),
        ("raw legacy wire", lambda: _raw_legacy_wire_check(exe)),
    )
    for name, probe in phases:
        try:
            await asyncio.wait_for(probe(), timeout=_PHASE_TIMEOUT)
        except TimeoutError:
            raise AssertionError(f"{name} phase timed out") from None
        except AssertionError:
            raise
        except Exception as exc:
            # Name the failing phase in CI output instead of a raw traceback.
            raise AssertionError(f"{name} phase failed: {exc!r}") from exc
    print(
        "stdio smoke OK: sessionless path negotiated, legacy handshake + "
        "camelCase wire keys, deadline-bounded reads, clean shutdown"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (TimeoutError, AssertionError) as exc:
        sys.exit(f"stdio smoke FAILED: {exc}")
