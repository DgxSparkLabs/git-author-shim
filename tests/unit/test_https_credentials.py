"""Unit tests for host-scoped HTTPS credentials (T024)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from uv_shims.git import credential_injector
from uv_shims.git.credential_injector import (
    CredentialError,
    build_https_credential_flags,
    resolve_token,
)
from uv_shims.git.data_models import BotIdentity, HTTPSCredential


def _identity(credential: HTTPSCredential) -> BotIdentity:
    return BotIdentity(
        id="bot",
        name="Automation Bot",
        email="bot@example.com",
        match_patterns=("github.com/example/*",),
        https=credential,
    )


def test_https_flags_reset_and_install_only_the_matched_host_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "do-not-put-this-token-in-argv"
    monkeypatch.setenv("BOT_TOKEN", secret)
    identity = _identity(HTTPSCredential(token_env_var="BOT_TOKEN"))

    flags = build_https_credential_flags(identity, "github.com")

    assert flags[0:2] == ["-c", "credential.https://github.com.helper="]
    assert flags[2] == "-c"
    assert flags[3].startswith("credential.https://github.com.helper=!")
    assert "credential.helper=" not in flags
    assert secret not in " ".join(flags)
    assert secret not in repr(flags)


def test_https_flags_include_username_without_exposing_token() -> None:
    identity = _identity(HTTPSCredential(token_env_var="PRIVATE_TOKEN", username="oauth2"))

    flags = build_https_credential_flags(identity, "gitlab.com")

    helper = flags[3]
    assert "oauth2" in helper
    assert "PRIVATE_TOKEN" in helper
    assert "credential.https://gitlab.com.helper=" in flags[1]
    assert "credential.https://gitlab.com.helper=" in helper


def test_resolve_token_from_environment_variable() -> None:
    credential = HTTPSCredential(token_env_var="BOT_TOKEN")

    assert resolve_token(credential, env={"BOT_TOKEN": "env-secret\n"}) == "env-secret"


def test_resolve_token_from_file(tmp_path: Path) -> None:
    token_file = tmp_path / "bot token.txt"
    token_file.write_text("file-secret\r\n", encoding="utf-8")
    credential = HTTPSCredential(token_file=token_file)

    assert resolve_token(credential, env={}) == "file-secret"


def test_resolve_token_from_external_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_run(command: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs["shell"] is True))
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(command, 0, stdout="command-secret\n", stderr="")

    monkeypatch.setattr(credential_injector.subprocess, "run", fake_run)
    credential = HTTPSCredential(token_command="secret-tool lookup bot")

    assert resolve_token(credential, env={}) == "command-secret"
    assert calls == [("secret-tool lookup bot", True)]


def test_missing_token_error_never_contains_secret_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaked_output = "TOP-SECRET-command-output"

    def fake_run(command: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            9,
            stdout=leaked_output,
            stderr=f"backend failed after reading {leaked_output}",
        )

    monkeypatch.setattr(credential_injector.subprocess, "run", fake_run)
    credential = HTTPSCredential(token_command="secret-tool lookup bot")

    with pytest.raises(CredentialError) as caught:
        resolve_token(credential, env={})

    assert leaked_output not in str(caught.value)
    assert "token command failed" in str(caught.value)
