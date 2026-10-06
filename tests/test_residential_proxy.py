"""
tests/test_residential_proxy.py
Tests for the RFC 1928 SOCKS5 residential proxy server.
"""
from __future__ import annotations

import asyncio
import struct
import pytest

from komdigi_bot.service.residential_proxy import (
    ResidentialSocks5Server,
    SOCKS_VERSION,
    METHOD_NO_AUTH,
    CMD_CONNECT,
    ATYP_IPV4,
    REP_SUCCESS,
)


@pytest.mark.anyio
async def test_socks5_handshake_and_connect():
    # 1. Start an echo target server
    received_echo = bytearray()

    async def handle_echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        data = await reader.read(100)
        received_echo.extend(data)
        writer.write(b"ECHO:" + data)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    echo_server = await asyncio.start_server(handle_echo, "127.0.0.1", 0)
    echo_port = echo_server.sockets[0].getsockname()[1]

    # 2. Start SOCKS5 proxy server
    proxy_server = ResidentialSocks5Server("127.0.0.1", 0)
    await proxy_server.start()
    proxy_port = proxy_server._server.sockets[0].getsockname()[1]

    try:
        # 3. Connect client to proxy
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)

        # Handshake: version 5, 1 method (0x00: no auth)
        writer.write(struct.pack("!BB", SOCKS_VERSION, 1) + bytes([METHOD_NO_AUTH]))
        await writer.drain()

        handshake_resp = await reader.read(2)
        assert handshake_resp == struct.pack("!BB", SOCKS_VERSION, METHOD_NO_AUTH)

        # Connect command: CMD_CONNECT to 127.0.0.1:echo_port
        ip_bytes = bytes([127, 0, 0, 1])
        req = struct.pack("!BBBB", SOCKS_VERSION, CMD_CONNECT, 0, ATYP_IPV4) + ip_bytes + struct.pack("!H", echo_port)
        writer.write(req)
        await writer.drain()

        resp = await reader.read(10)
        assert len(resp) == 10
        ver, rep, rsv, atyp = struct.unpack("!BBBB", resp[:4])
        assert ver == SOCKS_VERSION
        assert rep == REP_SUCCESS

        # Send payload through the tunnel
        writer.write(b"HELLO_KOMDIGI")
        await writer.drain()

        reply = await reader.read(100)
        assert reply == b"ECHO:HELLO_KOMDIGI"
        assert received_echo == b"HELLO_KOMDIGI"

        writer.close()
        await writer.wait_closed()

    finally:
        await proxy_server.stop()
        echo_server.close()
        await echo_server.wait_closed()
