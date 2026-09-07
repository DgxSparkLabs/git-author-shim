"""Contract tests for the ``git-shim trust`` / ``git-shim untrust`` CLI (T040, US8).

Exercises the console-script entry point ``uv_shims.git.cli:main`` exactly as
an operator would: ``git-shim trust <file>`` records the file's SHA-256 in the
operator registry, ``git-shim untrust <file>`` removes it, and repository-local
configuration is ignored by command resolution until trusted (FR-030,
contracts/cli.md §3.1).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from uv_shims.git.cli import main
from uv_shims.git.config import load_local_config
from uv_shims.git.repo_config_trust import (
    default_registry_path,
    is_config_trusted,
)

LOCAL_CONFIG_BODY = """
identity = "acme-github"

[override]
name = "Acme Release Bot"
email = "release-bot@acme.test"
"""


def write_local_config(tmp_path: Path, content: str = LOCAL_CONFIG_BODY) -> Path:
    path = tmp_path / ".git-shim.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_trust_subcommand_records_the_file_hash(
    tmp_path: Path, isolated_env, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_local_config(tmp_path)

    exit_code = main(["trust", str(path)])

    assert exit_code == 0
    expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    assert expected_hash in capsys.readouterr().out
    registry = json.loads(default_registry_path().read_text(encoding="utf-8"))
    assert registry["trusted"][str(path.resolve())] == expected_hash
    assert is_config_trusted(path) is True


def test_untrust_subcommand_removes_the_file_hash(
    tmp_path: Path, isolated_env, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_local_config(tmp_path)
    assert main(["trust", str(path)]) == 0

    exit_code = main(["untrust", str(path)])

    assert exit_code == 0
    assert "untrusted" in capsys.readouterr().out
    registry = json.loads(default_registry_path().read_text(encoding="utf-8"))
    assert registry["trusted"] == {}
    assert is_config_trusted(path) is False


def test_trust_then_untrust_round_trips_through_command_resolution(
    tmp_path: Path, isolated_env
) -> None:
    """Untrusted local configs are ignored; trusted ones resolve."""
    path = write_local_config(tmp_path)

    # Before trust: the local config is ignored during resolution.
    assert load_local_config(path) is None

    assert main(["trust", str(path)]) == 0
    resolved = load_local_config(path)
    assert resolved is not None
    assert resolved.identity == "acme-github"

    # Tampering revokes the grant without any CLI action.
    path.write_text('identity = "attacker-bot"\n', encoding="utf-8")
    assert load_local_config(path) is None

    # Re-trust the new content, then untrust: ignored again.
    assert main(["trust", str(path)]) == 0
    assert load_local_config(path) is not None
    assert main(["untrust", str(path)]) == 0
    assert load_local_config(path) is None


def test_trust_of_a_missing_file_fails_with_exit_code_2(
    tmp_path: Path, isolated_env, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["trust", str(tmp_path / "does-not-exist.toml")])

    assert exit_code == 2
    assert "does-not-exist" in capsys.readouterr().err
    assert not default_registry_path().exists()


def test_untrust_of_a_never_trusted_file_succeeds_without_a_grant(
    tmp_path: Path, isolated_env, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_local_config(tmp_path)

    exit_code = main(["untrust", str(path)])

    assert exit_code == 0
    assert "not trusted" in capsys.readouterr().out
    assert is_config_trusted(path) is False
