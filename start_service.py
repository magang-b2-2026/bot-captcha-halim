"""
start_service.py — Entry point untuk menjalankan komdigi-bot sebagai service.
Menginisialisasi structured logging ke file + stdout sebelum server mulai.

Usage:
    uv run python start_service.py [--port 8080] [--host 0.0.0.0]
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(log_dir: Path = Path("outputs/logs")) -> None:
    """Setup structured logging: JSON ke file + human-readable ke stdout."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "service.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # File handler — rotating, max 10 MB, 5 backup files
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
        )
    )
    root.addHandler(fh)

    # Stdout handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%H:%M:%S")
    )
    root.addHandler(sh)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # kurangi noise


def main() -> None:
    parser = argparse.ArgumentParser(description="komdigi-bot captcha service")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Hot-reload (dev only)")
    args = parser.parse_args()

    setup_logging()

    logger = logging.getLogger("komdigi_bot.main")
    logger.info("=" * 60)
    logger.info("komdigi-bot Service starting")
    logger.info("Host: %s  Port: %d", args.host, args.port)
    logger.info("Docs: http://localhost:%d/docs", args.port)
    logger.info("=" * 60)

    import uvicorn

    uvicorn.run(
        "komdigi_bot.service.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",  # uvicorn logs — pakai logger kita sendiri
        access_log=False,
    )


if __name__ == "__main__":
    main()
