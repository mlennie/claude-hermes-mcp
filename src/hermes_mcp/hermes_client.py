"""Subprocess wrapper for the hermes CLI.

This module is the **only** place that knows the hermes CLI flag surface.
We invoke hermes via its public CLI (`hermes -z`, `hermes --continue`,
`hermes --toolsets`) and never import private hermes Python modules — the
CLI is the stable contract across hermes versions.

Security:
  - argv is always a list; `shell=True` is never used.
  - timeout is enforced.
  - prompt bodies are NOT logged at INFO level (privacy by default).
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class HermesError(Exception):
    """Raised when a hermes invocation fails."""


@dataclass(frozen=True)
class HermesResult:
    stdout: str
    stderr: str
    returncode: int


class HermesClient:
    """Invokes the hermes CLI in one-shot mode."""

    def __init__(
        self,
        hermes_bin: str,
        timeout_seconds: int,
        default_toolsets: Sequence[str] = (),
    ) -> None:
        self._bin = hermes_bin
        self._timeout = timeout_seconds
        self._default_toolsets = tuple(default_toolsets)

    def ask(
        self,
        prompt: str,
        session_id: str | None = None,
        toolsets: Sequence[str] | None = None,
    ) -> str:
        """Send `prompt` to hermes and return its final response text.

        If `session_id` is provided, hermes continues that session
        (`hermes --continue <id>`). Otherwise a fresh one-shot invocation.
        """
        argv = self._build_argv(prompt, session_id=session_id, toolsets=toolsets)
        result = self._run(argv)
        return result.stdout.strip()

    def _build_argv(
        self,
        prompt: str,
        session_id: str | None,
        toolsets: Sequence[str] | None,
    ) -> list[str]:
        argv: list[str] = [self._bin]

        effective_toolsets = tuple(toolsets) if toolsets is not None else self._default_toolsets
        if effective_toolsets:
            argv.extend(["-t", ",".join(effective_toolsets)])

        if session_id:
            argv.extend(["--continue", session_id])

        argv.extend(["-z", prompt])
        return argv

    def _run(self, argv: list[str]) -> HermesResult:
        logger.info(
            "hermes invoke argc=%d session=%s timeout=%ds",
            len(argv),
            "y" if "--continue" in argv else "n",
            self._timeout,
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("hermes argv: %s", argv)

        try:
            completed = subprocess.run(  # noqa: S603 — argv list, shell=False
                argv,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HermesError(f"hermes timed out after {self._timeout}s") from exc
        except OSError as exc:
            raise HermesError(f"failed to invoke hermes ({argv[0]}): {exc}") from exc

        if completed.returncode != 0:
            tail = (completed.stderr or "").strip()[-500:]
            raise HermesError(f"hermes exited {completed.returncode}: {tail}")

        return HermesResult(
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            returncode=completed.returncode,
        )
