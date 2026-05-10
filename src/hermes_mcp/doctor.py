"""Startup self-checks. Verifies the Hermes gateway is reachable and the
configured API key works.

Fails loudly with actionable messages — never a Python traceback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from .config import Config

logger = logging.getLogger(__name__)


class DoctorError(Exception):
    """Raised when a startup check fails."""


@dataclass(frozen=True)
class DoctorResult:
    gateway_url: str
    gateway_models: tuple[str, ...]


def run_checks(config: Config) -> DoctorResult:
    health_url = config.hermes_api_url.rstrip("/") + "/v1/health"
    try:
        health = httpx.get(health_url, timeout=5, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise DoctorError(
            f"hermes gateway unreachable at {health_url}: {exc}. "
            "Is `hermes-gateway` running? `systemctl --user status hermes-gateway`."
        ) from exc
    if health.status_code != 200:
        raise DoctorError(
            f"hermes gateway returned {health.status_code} on /v1/health "
            f"(expected 200). url={health_url}"
        )

    models_url = config.hermes_api_url.rstrip("/") + "/v1/models"
    try:
        models = httpx.get(
            models_url,
            headers={"Authorization": f"Bearer {config.hermes_api_key}"},
            timeout=5,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise DoctorError(f"hermes gateway /v1/models request failed: {exc}") from exc
    if models.status_code == 401:
        raise DoctorError(
            "hermes gateway rejected the API key (401 on /v1/models). "
            "Check HERMES_API_KEY matches API_SERVER_KEY in ~/.hermes/.env."
        )
    if models.status_code != 200:
        raise DoctorError(
            f"hermes gateway /v1/models returned {models.status_code} "
            f"(expected 200). body: {models.text[:300]!r}"
        )

    try:
        data = models.json()
        model_ids = tuple(m["id"] for m in data.get("data", []))
    except (ValueError, KeyError, TypeError) as exc:
        raise DoctorError(f"hermes gateway /v1/models returned malformed JSON: {exc}") from exc

    if config.hermes_model not in model_ids:
        logger.warning(
            "configured HERMES_MODEL %r not in /v1/models %s — request may 404 at runtime",
            config.hermes_model,
            list(model_ids),
        )

    logger.info(
        "doctor: hermes gateway ok at %s — models=%s", config.hermes_api_url, list(model_ids)
    )
    return DoctorResult(gateway_url=config.hermes_api_url, gateway_models=model_ids)
