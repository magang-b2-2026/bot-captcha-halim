"""
komdigi_bot/service/residential_proxy.py
Lightweight asynchronous SOCKS5 proxy server (RFC 1928 compliant)
designed to run on the residential Mini PC node.

Enables the VPS Singapore 24/7 worker to route all browser scraping
and captcha egress traffic through the Mini PC's residential IP
via the encrypted Tailscale private mesh network.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import struct
from typing import Optional

logger = logging.getLogger("komdigi_bot.residential_proxy")

# SOCKS5 constants
SOCKS_VERSION = 5
METHOD_NO_AUTH = 0x00
METHOD_NO_ACCEPTABLE = 0xFF

CMD_CONNECT = 0x01

ATYP_IPV4 = 0x01
ATYP_DOMAINNAME = 0x03
ATYP_IPV6 = 0x04

REP_SUCCESS = 0x00
REP_GEN_FAILURE = 0x01
REP_CONN_NOT_ALLOWED = 0x02
REP_NETWORK_UNREACHABLE = 0x03
REP_HOST_UNREACHABLE = 0x04
REP_CONN_REFUSED = 0x05
REP_TTL_EXPIRED = 0x06
REP_CMD_NOT_SUPPORTED = 0x07
REP_ATYP_NOT_SUPPORTED = 0x08

BUFFER_SIZE = 65536


class ResidentialSocks5Server:
    """Async SOCKS5 proxy server binding to the specified host (e.g. Tailscale IP) and port."""

    def __init__(self, host: str = "0.0.0.0", port: int = 1080) -> None:
        self.host = host
        self.port = port
        self._server: Optional[asyncio.Server] = None
        self._active_connections = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self.handle_client,
            host=self.host,
            port=self.port,
        )
        addrs = ", ".join(str(sock.getsockname()) for sock in self._server.sockets)
        logger.info("Residential SOCKS5 Proxy listening on %s", addrs)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Residential SOCKS5 Proxy stopped.")

    async def handle_client(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        peer = client_writer.get_extra_info("peername")
        self._active_connections += 1
        logger.debug(
            "New proxy client connected from %s (Active: %d)", peer, self._active_connections
        )

        try:
            # 1. Greeting & Method Negotiation
            header = await client_reader.read(2)
            if len(header) < 2:
                client_writer.close()
                return

            ver, nmethods = struct.unpack("!BB", header)
            if ver != SOCKS_VERSION:
                logger.warning("Unsupported SOCKS version: %s from %s", ver, peer)
                client_writer.close()
                return

            methods = await client_reader.read(nmethods)
            if METHOD_NO_AUTH not in methods:
                # No supported authentication method
                client_writer.write(struct.pack("!BB", SOCKS_VERSION, METHOD_NO_ACCEPTABLE))
                await client_writer.drain()
                client_writer.close()
                return

            # Accept NO_AUTH
            client_writer.write(struct.pack("!BB", SOCKS_VERSION, METHOD_NO_AUTH))
            await client_writer.drain()

            # 2. Connection Request
            req_header = await client_reader.read(4)
            if len(req_header) < 4:
                client_writer.close()
                return

            ver, cmd, _, atyp = struct.unpack("!BBBB", req_header)
            if ver != SOCKS_VERSION or cmd != CMD_CONNECT:
                # Only CONNECT supported
                reply = struct.pack(
                    "!BBBBIH", SOCKS_VERSION, REP_CMD_NOT_SUPPORTED, 0, ATYP_IPV4, 0, 0
                )
                client_writer.write(reply)
                await client_writer.drain()
                client_writer.close()
                return

            target_host: str = ""
            if atyp == ATYP_IPV4:
                addr_bytes = await client_reader.read(4)
                target_host = socket.inet_ntop(socket.AF_INET, addr_bytes)
            elif atyp == ATYP_DOMAINNAME:
                domain_len = (await client_reader.read(1))[0]
                domain_bytes = await client_reader.read(domain_len)
                target_host = domain_bytes.decode("utf-8", errors="replace")
            elif atyp == ATYP_IPV6:
                addr_bytes = await client_reader.read(16)
                target_host = socket.inet_ntop(socket.AF_INET6, addr_bytes)
            else:
                reply = struct.pack(
                    "!BBBBIH", SOCKS_VERSION, REP_ATYP_NOT_SUPPORTED, 0, ATYP_IPV4, 0, 0
                )
                client_writer.write(reply)
                await client_writer.drain()
                client_writer.close()
                return

            port_bytes = await client_reader.read(2)
            target_port = struct.unpack("!H", port_bytes)[0]

            logger.info(
                "Proxy Tunneling %s -> %s:%d",
                peer[0] if peer else "unknown",
                target_host,
                target_port,
            )

            # 3. Connect to Target Host
            try:
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(target_host, target_port),
                    timeout=15.0,
                )
            except (asyncio.TimeoutError, OSError) as exc:
                logger.warning(
                    "Failed connecting to target %s:%d - %s", target_host, target_port, exc
                )
                reply = struct.pack(
                    "!BBBBIH", SOCKS_VERSION, REP_HOST_UNREACHABLE, 0, ATYP_IPV4, 0, 0
                )
                client_writer.write(reply)
                await client_writer.drain()
                client_writer.close()
                return

            # Success reply
            # Bound address 0.0.0.0:0
            reply = struct.pack("!BBBBIH", SOCKS_VERSION, REP_SUCCESS, 0, ATYP_IPV4, 0, 0)
            client_writer.write(reply)
            await client_writer.drain()

            # 4. Bidirectional Streaming Relay
            await asyncio.gather(
                self._relay(client_reader, remote_writer),
                self._relay(remote_reader, client_writer),
            )

        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as exc:
            logger.debug("Exception in proxy handler for %s: %s", peer, exc)
        finally:
            self._active_connections -= 1
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass

    async def _relay(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await reader.read(BUFFER_SIZE)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            pass
        finally:
            try:
                if not writer.is_closing():
                    writer.close()
            except Exception:
                pass


async def run_server(host: str = "0.0.0.0", port: int = 1080) -> None:
    server = ResidentialSocks5Server(host=host, port=port)
    await server.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await server.stop()
