"""SHA-256 content-hash trust registry for repository-local config (T039, US8).

Repository-local ``.git-shim.toml`` files can influence identity and credential
selection, so they are honored only after the operator explicitly allowlists
the file's exact content (FR-030). This module persists that allowlist as a
JSON registry mapping the file's resolved absolute path to the SHA-256 hex
digest of its bytes:

```json
{
  "version": 1,
  "trusted": {
    "C:/path/to/repo/.git-shim.toml": "9f86d08..."
  }
}
```

Any modification to a trusted file changes its digest and therefore revokes
the grant until the operator re-trusts it. A missing or corrupt registry
trusts nothing (fail closed); the next ``trust_config`` call rebuilds it.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

__all__ = [
    "LOCAL_CONFIG_NAME",
    "REGISTRY_NAME",
    "TrustError",
    "compute_file_hash",
    "default_registry_path",
    "is_config_trusted",
    "trust_config",
    "untrust_config",
]

#: File name of the repository-local shim configuration.
LOCAL_CONFIG_NAME = ".git-shim.toml"

#: File name of the operator-owned trust registry inside the shim config dir.
REGISTRY_NAME = "trusted-hashes.json"

_REGISTRY_VERSION = 1


class TrustError(ValueError):
    """Raised when a file cannot be hashed or the registry cannot be written."""


def default_registry_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the platform-appropriate trust registry path.

    Mirrors :func:`uv_shims.git.config.default_config_path` but never follows
    the ``UV_SHIM_GIT_CONFIG`` override: the registry is operator state, not
    part of an overridable configuration file.
    """

    environment = os.environ if env is None else env
    if os.name == "nt":
        base = environment.get("APPDATA")
        if base:
            return Path(base) / "uv-shims" / REGISTRY_NAME
    else:
        base = environment.get("XDG_CONFIG_HOME")
        if base:
            return Path(base) / "uv-shims" / REGISTRY_NAME
    return Path.home() / ".config" / "uv-shims" / REGISTRY_NAME


def compute_file_hash(path: str | os.PathLike[str]) -> str:
    """Return the SHA-256 hex digest of the file's raw bytes."""

    file_path = Path(path)
    try:
        return hashlib.sha256(file_path.read_bytes()).hexdigest()
    except OSError as error:
        raise TrustError(f"cannot hash {file_path}: {error}") from error


def is_config_trusted(
    path: str | os.PathLike[str], *, registry_path: str | os.PathLike[str] | None = None
) -> bool:
    """Return ``True`` only when the file's current content hash is allowlisted.

    Fails closed: a missing file, a missing registry, a corrupt registry, or a
    hash mismatch all read as untrusted.
    """

    file_path = Path(path)
    if not file_path.is_file():
        return False
    trusted = _load_registry(registry_path)
    recorded = trusted.get(_registry_key(file_path))
    if not isinstance(recorded, str):
        return False
    try:
        return compute_file_hash(file_path) == recorded
    except TrustError:
        return False


def trust_config(
    path: str | os.PathLike[str], *, registry_path: str | os.PathLike[str] | None = None
) -> str:
    """Record the file's current SHA-256 in the registry and return the digest."""

    file_path = Path(path)
    digest = compute_file_hash(file_path)
    registry_file = _registry_file(registry_path)
    trusted = _load_registry(registry_file)
    trusted[_registry_key(file_path)] = digest
    _write_registry(registry_file, trusted)
    return digest


def untrust_config(
    path: str | os.PathLike[str], *, registry_path: str | os.PathLike[str] | None = None
) -> bool:
    """Remove the file from the registry; return whether an entry was removed."""

    registry_file = _registry_file(registry_path)
    trusted = _load_registry(registry_file)
    if trusted.pop(_registry_key(Path(path)), None) is None:
        return False
    _write_registry(registry_file, trusted)
    return True


def _registry_file(registry_path: str | os.PathLike[str] | None) -> Path:
    return default_registry_path() if registry_path is None else Path(registry_path)


def _registry_key(path: Path) -> str:
    """Canonical registry key for a config file: its resolved absolute path."""

    return str(path.expanduser().resolve())


def _load_registry(registry_path: str | os.PathLike[str] | None) -> dict[str, str]:
    """Read the trusted map, treating anything unreadable as empty (fail closed)."""

    registry_file = _registry_file(registry_path)
    try:
        raw: Any = json.loads(registry_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    trusted = raw.get("trusted")
    if not isinstance(trusted, dict):
        return {}
    return {key: value for key, value in trusted.items() if isinstance(value, str)}


def _write_registry(registry_file: Path, trusted: Mapping[str, str]) -> None:
    """Persist the trusted map atomically (temp file + replace)."""

    payload = json.dumps(
        {"version": _REGISTRY_VERSION, "trusted": dict(sorted(trusted.items()))},
        indent=2,
    )
    try:
        registry_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = registry_file.with_name(registry_file.name + ".tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        os.replace(temporary, registry_file)
    except OSError as error:
        raise TrustError(f"cannot write trust registry {registry_file}: {error}") from error
