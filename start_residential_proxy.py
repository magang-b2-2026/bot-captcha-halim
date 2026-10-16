"""
start_residential_proxy.py — Entry point untuk menjalankan Residential SOCKS5 Proxy pada Mini PC.

Menyediakan egress proxy residential bagi worker 24/7 di VPS
melalui jaringan privat terenkripsi Tailscale / WireGuard mesh.

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

# Ensure src/ is in sys.path
_SRC_DIR = Path(__file__).resolve().parent / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

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

    # Stdout handler (only if console is attached)
    if sys.stdout is not None:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S"
        ))
        root.addHandler(sh)


def main() -> None:
    parser = argparse.ArgumentParser(description="komdigi-bot residential SOCKS5 proxy server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=1080, help="Bind port (default: 1080)")
    args = parser.parse_args()

    setup_logging()

    logger = logging.getLogger("komdigi_bot.proxy_main")
    logger.info("=" * 60)
    logger.info("KOMDIGI Residential SOCKS5 Proxy Starting")
    logger.info("Listening on: %s:%d", args.host, args.port)
    logger.info("Access: socks5://<tailscale-ip>:%d", args.port)
    logger.info("=" * 60)

    from komdigi_bot.service.residential_proxy import run_server

    try:
        asyncio.run(run_server(host=args.host, port=args.port))
    except (KeyboardInterrupt, SystemExit):
        logger.info("Proxy server shutdown signal received.")


if __name__ == "__main__":
    main()
