#!/usr/bin/env python3
"""Standalone Playwright stub that exposes a minimal WebSocket endpoint."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import signal
from typing import Dict

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, stop_event: asyncio.Event) -> None:
    """Accept a WebSocket handshake and keep the connection alive until shutdown."""

    try:
        request = await reader.readuntil(b"\r\n\r\n")
    except asyncio.IncompleteReadError:
        writer.close()
        await writer.wait_closed()
        return

    headers = _parse_headers(request.decode("utf-8", errors="ignore"))
    key = headers.get("sec-websocket-key")
    if key is None:
        writer.close()
        await writer.wait_closed()
        return

    accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    writer.write(response.encode())
    await writer.drain()

    try:
        await stop_event.wait()
    finally:
        writer.close()
        await writer.wait_closed()


def _parse_headers(request: str) -> Dict[str, str]:
    """Parse HTTP headers from a raw handshake request."""

    headers: Dict[str, str] = {}
    for line in request.splitlines()[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return headers


async def run() -> None:
    """Start the stub server and print a Playwright-style ``wsEndpoint`` line."""

    parser = argparse.ArgumentParser(description="Run a stub Playwright server")
    parser.add_argument("command", nargs="?", default="launch-server")
    parser.add_argument("browser", nargs="?", default="camoufox")
    args = parser.parse_args()
    if args.command != "launch-server":
        raise SystemExit(f"unsupported command: {args.command}")

    stop_event = asyncio.Event()

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await handle_client(reader, writer, stop_event)

    server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    sockets = server.sockets
    assert sockets is not None
    port = sockets[0].getsockname()[1]
    endpoint = f"ws://127.0.0.1:{port}/playwright"
    print(json.dumps({"wsEndpoint": endpoint}), flush=True)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows fallback
            pass

    await stop_event.wait()
    server.close()
    await server.wait_closed()


def main() -> int:
    """Entry point compatible with ``python stub.py`` execution."""

    try:
        asyncio.run(run())
    except KeyboardInterrupt:  # pragma: no cover - manual interrupts
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
