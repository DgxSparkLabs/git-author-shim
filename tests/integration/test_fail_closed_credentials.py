"""Integration tests for credential and effective-destination refusal (T042/T043)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"


def _shim_env(real_git: str, **overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + existing if existing else "")
    env["UV_SHIM_GIT_REAL_PATH"] = real_git
    env["UV_SHIM_GIT_MODE"] = "agent"
    env.update(overrides)
    return env


def _run_shim(repo, fake_git, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "git_author_shim", *args],
        cwd=repo.path,
        env=_shim_env(str(fake_git.path)),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _configure_ssh_identity(isolated_env, key_file: Path) -> None:
    isolated_env.write_config(
        "[[identities]]\n"
        'id = "acme"\n'
        'name = "Acme Bot"\n'
        'email = "bot@acme.invalid"\n'
        'match_patterns = ["github.com/acme/*"]\n\n'
        "[identities.ssh]\n"
        f"key_file = {json.dumps(str(key_file))}\n"
    )


def test_missing_ssh_key_aborts_push_without_operator_fallback(
    isolated_env, temp_repo, fake_git, tmp_path
) -> None:
    missing_key = tmp_path / "missing-bot-key"
    _configure_ssh_identity(isolated_env, missing_key)
    operator_key = isolated_env.home / ".ssh" / "id_ed25519"
    operator_key.parent.mkdir()
    operator_key.write_text("operator private key", encoding="utf-8")
    repo = temp_repo("missing-key", remotes={"origin": "git@github.com:acme/app.git"})
    repo.config("core.sshCommand", f"ssh -i {operator_key}")

    result = _run_shim(repo, fake_git, "push", "origin", "main")

    assert result.returncode == 1
    assert "missing-bot-key" in result.stderr
    assert "SSH key" in result.stderr
    assert fake_git.call_count == 0


def test_explicit_foreign_push_destination_aborts_before_git_runs(
    isolated_env, temp_repo, fake_git, tmp_path
) -> None:
    key_file = tmp_path / "bot-key"
    key_file.write_text("bot private key", encoding="utf-8")
    _configure_ssh_identity(isolated_env, key_file)
    repo = temp_repo("foreign-destination", remotes={"origin": "git@github.com:acme/app.git"})

    result = _run_shim(
        repo,
        fake_git,
        "push",
        "git@untrusted.example:thief/repo.git",
        "HEAD:main",
    )

    assert result.returncode == 1
    assert "untrusted.example/thief/repo" in result.stderr
    assert fake_git.call_count == 0


@pytest.mark.parametrize("rewrite_key", ["insteadOf", "pushInsteadOf"])
def test_url_rewrite_to_untrusted_host_aborts_before_network_connection(
    isolated_env, temp_repo, fake_git, tmp_path, rewrite_key
) -> None:
    key_file = tmp_path / "bot-key"
    key_file.write_text("bot private key", encoding="utf-8")
    _configure_ssh_identity(isolated_env, key_file)
    repo = temp_repo("rewritten-destination", remotes={"origin": "git@github.com:acme/app.git"})
    repo.config(f"url.git@untrusted.example:.{rewrite_key}", "git@github.com:")

    result = _run_shim(repo, fake_git, "push", "origin", "main")

    assert result.returncode == 1
    assert "untrusted.example/acme/app" in result.stderr
    assert fake_git.call_count == 0
