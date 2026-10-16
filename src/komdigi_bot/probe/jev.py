"""Jev key validation probe.

Run as a module::

    uv run python -m komdigi_bot.probe.jev

This makes ONE cheap ``noul`` call ("Is 2+2=4?") against
``api.typesafe.ai/v1/systemone`` using the key in your ``.env`` and writes
``outputs/evidence/jev-probe.json`` with the full answer + usage.

Exit code:
    0 — probe succeeded, key is valid, answer written to evidence.
    1 — probe failed (auth error, network error, schema mismatch).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from komdigi_bot.config import get_settings
from komdigi_bot.decision.jev import (
    JevAuthError,
    JevClient,
    JevQuestion,
    JevRequest,
    JevResponseError,
    JevServerError,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("komdigi_bot.probe.jev")

_EVIDENCE_PATH = Path("outputs/evidence/jev-probe.json")


def run() -> int:
    """Run the validation probe. Returns 0 on success, 1 on failure."""
    settings = get_settings()

    if not settings.typesafe_api_key:
        logger.error("TYPESAFE_API_KEY is not set in .env — obtain one from console.typesafe.ai")
        _write_error("TYPESAFE_API_KEY not set")
        return 1

    logger.info("Probing Jev SystemOne at %s …", settings.jev.endpoint)

    try:
        client = JevClient(
            api_key=settings.typesafe_api_key,
            endpoint=settings.jev.endpoint,
            timeout=float(settings.jev.timeout_seconds),
        )
    except JevAuthError as exc:
        logger.error("Auth config error: %s", exc)
        _write_error(str(exc))
        return 1

    # One cheap noul question — minimal cost, unambiguous expected answer
    request = JevRequest(
        model=settings.jev.model,
        state="Simple arithmetic: 2+2=4",
        questions={
            "sanity": JevQuestion(
                type="noul",
                instructions="Is the statement in the state mathematically true?",
            )
        },
    )

    try:
        response = client.ask(request)
    except JevAuthError as exc:
        logger.error(
            "Authentication failed — check TYPESAFE_API_KEY (console.typesafe.ai): %s", exc
        )
        _write_error(str(exc))
        return 1
    except JevServerError as exc:
        logger.error("Jev server error (transient): %s", exc)
        _write_error(str(exc))
        return 1
    except JevResponseError as exc:
        logger.error("Jev response malformed: %s", exc)
        _write_error(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error: %s", exc)
        _write_error(str(exc))
        return 1

    noul_answer = response.noul("sanity")
    evidence = {
        "status": "ok",
        "resolved_model": response.model,
        "answers": response.answers,
        "noul_value": noul_answer.noul,
        "noul_is_true": noul_answer.is_true,
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        },
    }
    _write_evidence(evidence)
    logger.info(
        "Probe SUCCESS — model=%s noul=%.4f (expected ~1.0) usage_total=%d",
        response.model,
        noul_answer.noul,
        response.usage.total_tokens,
    )
    return 0


def _write_evidence(data: dict[str, Any]) -> None:
    _EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _EVIDENCE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Evidence written to %s", _EVIDENCE_PATH)


def _write_error(message: str) -> None:
    _EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _EVIDENCE_PATH.write_text(
        json.dumps({"status": "error", "message": message}, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(run())
