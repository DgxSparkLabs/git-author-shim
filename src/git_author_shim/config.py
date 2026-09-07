"""Load and validate the operator-owned Git shim configuration."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .data_models import (
    BotIdentity,
    GlobalSettings,
    HTTPSCredential,
    IdentityMode,
    ShimConfig,
    SSHCredential,
)
from .repo_config_trust import LOCAL_CONFIG_NAME, is_config_trusted


class ConfigError(ValueError):
    """Raised when a shim configuration file cannot be parsed or validated."""


@dataclass(frozen=True, slots=True)
class LocalConfig:
    """Validated repository-local ``.git-shim.toml`` overrides (US8).

    Carries no secrets: repository-local files may select an identity and
    override its display name/email, but credential fields are rejected at
    parse time (FR-030).
    """

    identity: str | None = None
    name: str | None = None
    email: str | None = None


def default_config_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the operator-owned global configuration path.

    Precedence: ``GIT_SHIM_CONFIG``, then ``~/.git-shim/config.toml``. If
    ``config.toml`` is absent but ``~/.git-shim/git.toml`` exists, that legacy
    filename is used instead.
    """

    environment = os.environ if env is None else env
    override = environment.get("GIT_SHIM_CONFIG")
    if override:
        return Path(override)
    config_dir = Path.home() / ".git-shim"
    config_path = config_dir / "config.toml"
    if not config_path.exists():
        legacy = config_dir / "git.toml"
        if legacy.exists():
            return legacy
    return config_path


def load_config(path: str | os.PathLike[str] | None = None) -> ShimConfig:
    """Parse and validate the global configuration into immutable data models.

    ``tomllib`` is imported only when a configuration file is actually read, so
    startup paths that bypass agent configuration do not pay its import cost.
    """

    config_path = default_config_path() if path is None else Path(path)
    if not config_path.exists():
        return ShimConfig()

    import tomllib

    try:
        with config_path.open("rb") as config_file:
            parsed = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {config_path}: {error}") from error
    except OSError as error:
        raise ConfigError(f"cannot read configuration {config_path}: {error}") from error

    return _parse_config(parsed)


def load_local_config(
    path: str | os.PathLike[str] | None = None,
    *,
    registry_path: str | os.PathLike[str] | None = None,
) -> LocalConfig | None:
    """Parse a repository-local ``.git-shim.toml``, gated on operator trust.

    Returns ``None`` when the file does not exist or its current content hash
    is not in the trust registry (FR-030): untrusted or tampered files are
    silently ignored rather than honored. A trusted file is still validated,
    and any secret-bearing field is rejected with :class:`ConfigError`.
    """

    config_path = Path(LOCAL_CONFIG_NAME) if path is None else Path(path)
    if not config_path.exists():
        return None
    if not is_config_trusted(config_path, registry_path=registry_path):
        return None

    import tomllib

    try:
        with config_path.open("rb") as config_file:
            parsed = tomllib.load(config_file)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {config_path}: {error}") from error
    except OSError as error:
        raise ConfigError(f"cannot read configuration {config_path}: {error}") from error

    return _parse_local_config(parsed)


#: Fields that would let a repository smuggle in credential material; never
#: allowed in a repo-local file regardless of trust state (FR-030).
_LOCAL_SECRET_FIELDS = {
    "token",
    "token_env_var",
    "token_file",
    "token_command",
    "key_file",
    "ssh",
    "https",
    "identities",
}


def _parse_local_config(value: object) -> LocalConfig:
    root = _require_table(value, "local configuration")

    secrets = sorted(root.keys() & _LOCAL_SECRET_FIELDS)
    if secrets:
        names = ", ".join(secrets)
        raise ConfigError(
            f"local configuration must not contain secret or credential field(s): {names}"
        )
    _reject_unknown_fields(root, {"identity", "override"}, "local configuration")

    identity = root.get("identity")
    if identity is not None and (not isinstance(identity, str) or not identity.strip()):
        raise ConfigError("local configuration.identity must be a non-empty string")

    name: str | None = None
    email: str | None = None
    if "override" in root:
        override = _require_table(root["override"], "local configuration.override")
        _reject_unknown_fields(override, {"name", "email"}, "local configuration.override")
        name = _optional_string(override, "name", "local configuration.override")
        email = _optional_string(override, "email", "local configuration.override")

    return LocalConfig(identity=identity, name=name, email=email)


def _optional_string(table: Mapping[str, object], field: str, location: str) -> str | None:
    if field not in table:
        return None
    value = table[field]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{location}.{field} must be a non-empty string")
    return value


def _parse_config(value: object) -> ShimConfig:
    root = _require_table(value, "configuration")
    _reject_unknown_fields(root, {"settings", "identities"}, "configuration")

    settings_value = root.get("settings", {})
    settings = _parse_settings(settings_value)

    identities_value = root.get("identities", [])
    if not isinstance(identities_value, list):
        raise ConfigError("identities must be an array of tables")

    identities = tuple(
        _parse_identity(identity, index) for index, identity in enumerate(identities_value)
    )
    seen_ids: set[str] = set()
    for identity in identities:
        if identity.id in seen_ids:
            raise ConfigError(f"duplicate identity id: {identity.id!r}")
        seen_ids.add(identity.id)

    return ShimConfig(settings=settings, identities=identities)


def _parse_settings(value: object) -> GlobalSettings:
    settings = _require_table(value, "settings")
    _reject_unknown_fields(
        settings,
        {"default_mode", "vendor_detection", "custom_agent_markers"},
        "settings",
    )

    raw_mode = settings.get("default_mode", IdentityMode.AUTO.value)
    if not isinstance(raw_mode, str):
        raise ConfigError("settings.default_mode must be one of: auto, agent, human")
    try:
        default_mode = IdentityMode(raw_mode)
    except ValueError as error:
        raise ConfigError("settings.default_mode must be one of: auto, agent, human") from error

    vendor_detection = settings.get("vendor_detection", True)
    if type(vendor_detection) is not bool:
        raise ConfigError("settings.vendor_detection must be a boolean")

    custom_agent_markers = _string_list(
        settings.get("custom_agent_markers", []),
        "settings.custom_agent_markers",
        allow_empty=True,
    )
    return GlobalSettings(
        default_mode=default_mode,
        vendor_detection=vendor_detection,
        custom_agent_markers=custom_agent_markers,
    )


def _parse_identity(value: object, index: int) -> BotIdentity:
    location = f"identities[{index}]"
    identity = _require_table(value, location)
    _reject_unknown_fields(
        identity,
        {"id", "name", "email", "match_patterns", "ssh", "https"},
        location,
    )

    identity_id = _required_string(identity, "id", location)
    name = _required_string(identity, "name", location)
    email = _required_string(identity, "email", location)
    if "match_patterns" not in identity:
        raise ConfigError(f"{location}.match_patterns is required")
    match_patterns = _string_list(
        identity["match_patterns"],
        f"{location}.match_patterns",
        allow_empty=False,
    )

    ssh = _parse_ssh(identity["ssh"], f"{location}.ssh") if "ssh" in identity else None
    https = _parse_https(identity["https"], f"{location}.https") if "https" in identity else None
    return BotIdentity(
        id=identity_id,
        name=name,
        email=email,
        match_patterns=match_patterns,
        ssh=ssh,
        https=https,
    )


def _parse_ssh(value: object, location: str) -> SSHCredential:
    ssh = _require_table(value, location)
    _reject_unknown_fields(ssh, {"key_file", "strict_host_checking"}, location)
    key_file = _required_string(ssh, "key_file", location)
    strict_host_checking = ssh.get("strict_host_checking", True)
    if type(strict_host_checking) is not bool:
        raise ConfigError(f"{location}.strict_host_checking must be a boolean")
    return SSHCredential(
        key_file=Path(key_file),
        strict_host_checking=strict_host_checking,
    )


def _parse_https(value: object, location: str) -> HTTPSCredential:
    https = _require_table(value, location)
    token_sources = {"token_env_var", "token_file", "token_command"}
    _reject_unknown_fields(https, token_sources | {"username"}, location)

    present_sources = [source for source in token_sources if source in https]
    if len(present_sources) != 1:
        raise ConfigError(
            f"{location} must define exactly one token source: "
            "token_env_var, token_file, or token_command"
        )
    source = present_sources[0]
    source_value = _required_string(https, source, location)
    username = https.get("username", "x-access-token")
    if not isinstance(username, str) or not username.strip():
        raise ConfigError(f"{location}.username must be a non-empty string")

    return HTTPSCredential(
        token_env_var=source_value if source == "token_env_var" else None,
        token_file=Path(source_value) if source == "token_file" else None,
        token_command=source_value if source == "token_command" else None,
        username=username,
    )


def _require_table(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{location} must be a table")
    return value


def _required_string(table: Mapping[str, object], field: str, location: str) -> str:
    if field not in table:
        raise ConfigError(f"{location}.{field} is required")
    value = table[field]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{location}.{field} must be a non-empty string")
    return value


def _string_list(value: object, location: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ConfigError(f"{location} must be an array of non-empty strings")
    if not allow_empty and not value:
        raise ConfigError(f"{location} must contain at least one pattern")
    if len(set(value)) != len(value):
        raise ConfigError(f"{location} must not contain duplicates")
    return tuple(value)


def _reject_unknown_fields(table: Mapping[str, object], allowed: set[str], location: str) -> None:
    unknown = sorted(table.keys() - allowed)
    if unknown:
        names = ", ".join(unknown)
        raise ConfigError(f"{location} has unknown field(s): {names}")
