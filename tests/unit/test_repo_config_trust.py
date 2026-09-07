"""Unit tests for the SHA-256 content-hash trust registry (T038, US8).

Covers ``src/uv_shims/git/repo_config_trust.py`` and the trust-gated
repository-local config loading integrated into ``src/uv_shims/git/config.py``
(FR-030): a repo-local ``.git-shim.toml`` is ignored until its content hash is
allowlisted, tampering revokes the grant, and secret values are never read
from repo-local files.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from uv_shims.git.config import ConfigError, LocalConfig, load_local_config
from uv_shims.git.repo_config_trust import (
    TrustError,
    compute_file_hash,
    default_registry_path,
    is_config_trusted,
    trust_config,
    untrust_config,
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


def read_registry(registry_path: Path) -> dict[str, object]:
    return json.loads(registry_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------
# SHA-256 content hashing
# --------------------------------------------------------------------------------------


def test_compute_file_hash_matches_hashlib_sha256(tmp_path: Path) -> None:
    content = b'identity = "acme-github"\n'
    path = tmp_path / ".git-shim.toml"
    path.write_bytes(content)

    assert compute_file_hash(path) == hashlib.sha256(content).hexdigest()


def test_compute_file_hash_reads_raw_bytes(tmp_path: Path) -> None:
    content = b'identity = "bot"\r\nemail = "\xff\xfe binary \x00"\n'
    path = tmp_path / ".git-shim.toml"
    path.write_bytes(content)

    assert compute_file_hash(path) == hashlib.sha256(content).hexdigest()


def test_compute_file_hash_distinguishes_whitespace_only_changes(tmp_path: Path) -> None:
    path = tmp_path / ".git-shim.toml"
    path.write_bytes(b'identity = "bot"\n')
    before = compute_file_hash(path)
    path.write_bytes(b'identity = "bot"\r\n')

    assert compute_file_hash(path) != before


def test_compute_file_hash_missing_file_raises_trust_error(tmp_path: Path) -> None:
    with pytest.raises(TrustError, match="does-not-exist"):
        compute_file_hash(tmp_path / "does-not-exist.toml")


# --------------------------------------------------------------------------------------
# Registry location
# --------------------------------------------------------------------------------------


def test_default_registry_path_lives_in_the_shim_config_dir(isolated_env) -> None:
    assert default_registry_path() == isolated_env.shim_config_dir / "trusted-hashes.json"


# --------------------------------------------------------------------------------------
# trust / is_trusted / untrust lifecycle
# --------------------------------------------------------------------------------------


def test_untrusted_file_is_not_trusted_and_creates_no_registry(
    tmp_path: Path, isolated_env
) -> None:
    path = write_local_config(tmp_path)

    assert is_config_trusted(path) is False
    assert not default_registry_path().exists()


def test_trust_records_the_current_sha256_in_the_registry(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path)
    expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    recorded = trust_config(path)

    assert recorded == expected_hash
    registry = read_registry(default_registry_path())
    assert registry["trusted"][str(path.resolve())] == expected_hash
    assert is_config_trusted(path) is True


def test_trust_is_idempotent_and_keeps_a_single_entry(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path)

    first = trust_config(path)
    second = trust_config(path)

    assert first == second
    registry = read_registry(default_registry_path())
    assert list(registry["trusted"].values()) == [first]


def test_modifying_the_file_after_trust_revokes_the_grant(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path)
    trust_config(path)
    assert is_config_trusted(path) is True

    path.write_text(path.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    assert is_config_trusted(path) is False


def test_retrusting_after_modification_records_the_new_hash(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path)
    original = trust_config(path)

    path.write_text('identity = "other-bot"\n', encoding="utf-8")
    updated = trust_config(path)

    assert updated != original
    assert is_config_trusted(path) is True


def test_untrust_removes_the_registry_entry(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path)
    trust_config(path)

    removed = untrust_config(path)

    assert removed is True
    assert is_config_trusted(path) is False
    registry = read_registry(default_registry_path())
    assert registry["trusted"] == {}


def test_untrust_only_removes_the_named_file(tmp_path: Path, isolated_env) -> None:
    first = write_local_config(tmp_path)
    second = tmp_path / "other" / ".git-shim.toml"
    second.parent.mkdir()
    second.write_text('identity = "other-bot"\n', encoding="utf-8")
    trust_config(first)
    trust_config(second)

    untrust_config(first)

    assert is_config_trusted(first) is False
    assert is_config_trusted(second) is True


def test_untrust_of_a_never_trusted_file_returns_false(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path)

    assert untrust_config(path) is False
    assert is_config_trusted(path) is False


def test_trust_of_a_missing_file_raises_and_writes_nothing(tmp_path: Path, isolated_env) -> None:
    with pytest.raises(TrustError, match="does-not-exist"):
        trust_config(tmp_path / "does-not-exist.toml")

    assert not default_registry_path().exists()


def test_a_corrupt_registry_fails_closed_and_is_rebuilt_on_trust(
    tmp_path: Path, isolated_env
) -> None:
    path = write_local_config(tmp_path)
    registry_path = default_registry_path()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("{ not json", encoding="utf-8")

    # A registry that cannot be parsed trusts nothing (fail closed).
    assert is_config_trusted(path) is False

    # Re-trusting rebuilds a valid registry instead of crashing.
    trust_config(path)
    assert is_config_trusted(path) is True


def test_deleting_a_trusted_file_revokes_trust(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path)
    trust_config(path)

    path.unlink()

    assert is_config_trusted(path) is False


# --------------------------------------------------------------------------------------
# Trust-gated repository-local config loading (config.py integration)
# --------------------------------------------------------------------------------------


def test_load_local_config_returns_none_when_the_file_is_missing(
    tmp_path: Path, isolated_env
) -> None:
    assert load_local_config(tmp_path / ".git-shim.toml") is None


def test_load_local_config_ignores_an_untrusted_file(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path)

    assert load_local_config(path) is None


def test_load_local_config_parses_a_trusted_file(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path)
    trust_config(path)

    local = load_local_config(path)

    assert local == LocalConfig(
        identity="acme-github",
        name="Acme Release Bot",
        email="release-bot@acme.test",
    )


def test_load_local_config_ignores_a_file_modified_after_trust(
    tmp_path: Path, isolated_env
) -> None:
    path = write_local_config(tmp_path)
    trust_config(path)
    path.write_text('identity = "attacker-bot"\n', encoding="utf-8")

    assert load_local_config(path) is None


def test_load_local_config_honours_untrust(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path)
    trust_config(path)
    untrust_config(path)

    assert load_local_config(path) is None


@pytest.mark.parametrize(
    "secret_field",
    [
        'token = "ghp_literal"\n',
        'token_env_var = "BOT_TOKEN"\n',
        'token_file = "/run/secrets/token"\n',
        'token_command = "op read op://vault/item/token"\n',
        'key_file = "~/.ssh/stolen_key"\n',
        '[ssh]\nkey_file = "~/.ssh/stolen_key"\n',
        '[https]\ntoken_env_var = "BOT_TOKEN"\n',
        '[[identities]]\nid = "evil"\nname = "E"\nemail = "e@x.test"\nmatch_patterns = ["*"]\n',
    ],
)
def test_load_local_config_rejects_secret_material_even_when_trusted(
    tmp_path: Path, isolated_env, secret_field: str
) -> None:
    path = write_local_config(tmp_path, secret_field)
    trust_config(path)

    with pytest.raises(ConfigError, match="secret|credential|not allowed|unknown"):
        load_local_config(path)


def test_load_local_config_rejects_unknown_override_fields(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path, '[override]\nname = "Bot"\ngpg_key = "ABC"\n')
    trust_config(path)

    with pytest.raises(ConfigError, match="unknown field"):
        load_local_config(path)


def test_load_local_config_wraps_invalid_toml(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path, '[override\nname = "Bot"')
    trust_config(path)

    with pytest.raises(ConfigError, match="invalid TOML"):
        load_local_config(path)


def test_load_local_config_allows_partial_overrides(tmp_path: Path, isolated_env) -> None:
    path = write_local_config(tmp_path, 'identity = "acme-github"\n')
    trust_config(path)

    local = load_local_config(path)

    assert local == LocalConfig(identity="acme-github")
