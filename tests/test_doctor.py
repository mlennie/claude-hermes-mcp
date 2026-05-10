from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from hermes_mcp.config import Config
from hermes_mcp.doctor import DoctorError, run_checks

_VALID = {
    "OAUTH_CLIENT_ID": "hermes-mcp-test",
    "OAUTH_CLIENT_SECRET": "x" * 32,
    "OAUTH_ISSUER_URL": "https://hermes.example.com",
}


def _config(hermes_bin: str = "hermes") -> Config:
    return Config.from_env({**_VALID, "HERMES_BIN": hermes_bin})


def _completed(
    returncode: int = 0, stdout: str = "Hermes Agent v0.12.0\n", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_missing_binary_raises_actionable_error() -> None:
    cfg = _config(hermes_bin="definitely-not-a-real-binary-xyz")
    with pytest.raises(DoctorError, match="hermes binary not found"):
        run_checks(cfg)


def test_nonzero_version_exit_raises() -> None:
    cfg = _config()
    with (
        patch("hermes_mcp.doctor.shutil.which", return_value="/usr/bin/hermes"),
        patch("hermes_mcp.doctor.subprocess.run") as run,
    ):
        run.return_value = _completed(returncode=1, stderr="bad config")
        with pytest.raises(DoctorError, match="hermes --version exited 1"):
            run_checks(cfg)


def test_version_timeout_raises() -> None:
    cfg = _config()
    with (
        patch("hermes_mcp.doctor.shutil.which", return_value="/usr/bin/hermes"),
        patch("hermes_mcp.doctor.subprocess.run") as run,
    ):
        run.side_effect = subprocess.TimeoutExpired(cmd="hermes", timeout=15)
        with pytest.raises(DoctorError, match="timed out"):
            run_checks(cfg)


def test_version_first_line_returned() -> None:
    cfg = _config()
    with (
        patch("hermes_mcp.doctor.shutil.which", return_value="/usr/bin/hermes"),
        patch("hermes_mcp.doctor.subprocess.run") as run,
    ):
        run.return_value = _completed(stdout="Hermes Agent v1.2.3\nProject: /tmp\n")
        result = run_checks(cfg)
    assert result.hermes_version == "Hermes Agent v1.2.3"
    assert result.hermes_path == "/usr/bin/hermes"
