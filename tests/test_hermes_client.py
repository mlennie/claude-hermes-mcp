from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from hermes_mcp.hermes_client import HermesClient, HermesError


def _completed(
    returncode: int = 0, stdout: str = "ok", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_argv_stateless_minimal() -> None:
    client = HermesClient(hermes_bin="/usr/bin/hermes", timeout_seconds=60)
    argv = client._build_argv("hello", session_id=None, toolsets=None)
    assert argv == ["/usr/bin/hermes", "-z", "hello"]


def test_argv_with_session() -> None:
    client = HermesClient(hermes_bin="hermes", timeout_seconds=60)
    argv = client._build_argv("hi", session_id="sess-1", toolsets=None)
    assert argv == ["hermes", "--continue", "sess-1", "-z", "hi"]


def test_argv_with_call_toolsets_overrides_default() -> None:
    client = HermesClient(
        hermes_bin="hermes",
        timeout_seconds=60,
        default_toolsets=("web",),
    )
    argv = client._build_argv("hi", session_id=None, toolsets=["filesystem", "email"])
    assert argv == ["hermes", "-t", "filesystem,email", "-z", "hi"]


def test_argv_uses_default_toolsets() -> None:
    client = HermesClient(
        hermes_bin="hermes",
        timeout_seconds=60,
        default_toolsets=("web", "fs"),
    )
    argv = client._build_argv("hi", session_id=None, toolsets=None)
    assert argv == ["hermes", "-t", "web,fs", "-z", "hi"]


def test_argv_empty_call_toolsets_means_no_flag() -> None:
    client = HermesClient(
        hermes_bin="hermes",
        timeout_seconds=60,
        default_toolsets=("web",),
    )
    argv = client._build_argv("hi", session_id=None, toolsets=[])
    assert argv == ["hermes", "-z", "hi"]


def test_ask_returns_stripped_stdout() -> None:
    client = HermesClient(hermes_bin="hermes", timeout_seconds=60)
    with patch("hermes_mcp.hermes_client.subprocess.run") as run:
        run.return_value = _completed(stdout="  hermes says hi  \n")
        out = client.ask("ping")
    assert out == "hermes says hi"
    args, kwargs = run.call_args
    assert kwargs["timeout"] == 60
    assert kwargs.get("shell") is None or kwargs["shell"] is False
    assert args[0] == ["hermes", "-z", "ping"]


def test_ask_propagates_nonzero_exit() -> None:
    client = HermesClient(hermes_bin="hermes", timeout_seconds=60)
    with patch("hermes_mcp.hermes_client.subprocess.run") as run:
        run.return_value = _completed(returncode=2, stderr="boom")
        with pytest.raises(HermesError, match="hermes exited 2"):
            client.ask("ping")


def test_ask_propagates_timeout() -> None:
    client = HermesClient(hermes_bin="hermes", timeout_seconds=1)
    with patch("hermes_mcp.hermes_client.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd="hermes", timeout=1)
        with pytest.raises(HermesError, match="timed out"):
            client.ask("ping")


def test_ask_propagates_oserror() -> None:
    client = HermesClient(hermes_bin="hermes-missing", timeout_seconds=60)
    with patch("hermes_mcp.hermes_client.subprocess.run") as run:
        run.side_effect = FileNotFoundError("no such file")
        with pytest.raises(HermesError, match="failed to invoke hermes"):
            client.ask("ping")
