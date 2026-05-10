"""Startup self-checks. Verifies hermes is invocable and toolsets exist.

Fails loudly with actionable messages — never a Python traceback.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

from .config import Config

logger = logging.getLogger(__name__)


class DoctorError(Exception):
    """Raised when a startup check fails."""


@dataclass(frozen=True)
class DoctorResult:
    hermes_path: str
    hermes_version: str


def run_checks(config: Config) -> DoctorResult:
    resolved = shutil.which(config.hermes_bin)
    if resolved is None:
        raise DoctorError(
            f"hermes binary not found: {config.hermes_bin!r}. "
            "Install Hermes Agent or set HERMES_BIN to its absolute path."
        )
    hermes_path = resolved

    try:
        result = subprocess.run(  # noqa: S603 — argv list, no shell
            [hermes_path, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DoctorError(f"hermes --version timed out after 15s ({hermes_path})") from exc
    except OSError as exc:
        raise DoctorError(f"failed to invoke {hermes_path}: {exc}") from exc

    if result.returncode != 0:
        raise DoctorError(
            f"hermes --version exited {result.returncode}. stderr: {result.stderr.strip()[:500]}"
        )

    version = (
        (result.stdout or result.stderr).strip().splitlines()[0]
        if (result.stdout or result.stderr)
        else "unknown"
    )

    logger.info("doctor: hermes ok at %s — %s", hermes_path, version)
    return DoctorResult(hermes_path=hermes_path, hermes_version=version)
