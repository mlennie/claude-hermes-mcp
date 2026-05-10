from __future__ import annotations

import logging
import subprocess
from unittest.mock import patch

import pytest

from hermes_mcp.config import Config
from hermes_mcp.doctor import DoctorError, run_checks


def _config(token: str = "x" * 32, hermes_bin: str = "hermes") -> Config:
    return Config.from_env({"MCP_BEARER_TOKEN": token, "HERMES_BIN": hermes_bin})


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


def test_short_token_warns(caplog: pytest.LogCaptureFixture) -> None:
    cfg = _config(token="short")
    with (
        patch("hermes_mcp.doctor.shutil.which", return_value="/usr/bin/hermes"),
        patch("hermes_mcp.doctor.subprocess.run") as run,
        caplog.at_level(logging.WARNING, logger="hermes_mcp.doctor"),
    ):
        run.return_value = _completed()
        result = run_checks(cfg)
    assert result.hermes_path == "/usr/bin/hermes"
    assert any("shorter than 32" in rec.message for rec in caplog.records)


def test_long_token_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    cfg = _config(token="x" * 64)
    with (
        patch("hermes_mcp.doctor.shutil.which", return_value="/usr/bin/hermes"),
        patch("hermes_mcp.doctor.subprocess.run") as run,
        caplog.at_level(logging.WARNING, logger="hermes_mcp.doctor"),
    ):
        run.return_value = _completed()
        run_checks(cfg)
    assert not any("shorter than 32" in rec.message for rec in caplog.records)


def test_version_first_line_returned() -> None:
    cfg = _config()
    with (
        patch("hermes_mcp.doctor.shutil.which", return_value="/usr/bin/hermes"),
        patch("hermes_mcp.doctor.subprocess.run") as run,
    ):
        run.return_value = _completed(stdout="Hermes Agent v1.2.3\nProject: /tmp\n")
        result = run_checks(cfg)
    assert result.hermes_version == "Hermes Agent v1.2.3"
