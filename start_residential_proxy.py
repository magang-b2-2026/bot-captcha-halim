"""
start_residential_proxy.py — Entry point untuk menjalankan Residential SOCKS5 Proxy pada Mini PC.

Menyediakan egress proxy residential bagi worker 24/7 di VPS Singapore
melalui jaringan privat terenkripsi Tailscale (IP: 100.118.42.78).

Usage:
    uv run python start_residential_proxy.py [--host 0.0.0.0] [--port 1080]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import sys
from pathlib import Path

from komdigi_bot.service.residential_proxy import ResidentialSocks5Server


def setup_logging(log_dir: Path = Path("outputs/logs")) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "residential_proxy.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Rotating file handler
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))
    root.addHandler(fh)

    # Stdout handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    ))
    root.addHandler(sh)


def main() -> None:
    parser = argparse.ArgumentParser(description="komdigi-bot residential SOCKS5 proxy server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0 / 100.118.42.78)")
    parser.add_argument("--port", type=int, default=1080, help="Bind port (default: 1080)")
    args = parser.parse_args()

    setup_logging()

    logger = logging.getLogger("komdigi_bot.proxy_main")
    logger.info("=" * 60)
    logger.info("KOMDIGI Residential SOCKS5 Proxy Starting")
    logger.info("Listening on: %s:%d", args.host, args.port)
    logger.info("Tailscale Access: socks5://100.118.42.78:%d", args.port)
    logger.info("=" * 60)

    server = ResidentialSocks5Server(host=args.host, port=args.port)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(server.start())
        loop.run_forever()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal. Stopping proxy...")
        loop.run_until_complete(server.stop())
    finally:
        loop.close()
        logger.info("Proxy server shutdown complete.")


if __name__ == "__main__":
    main()
