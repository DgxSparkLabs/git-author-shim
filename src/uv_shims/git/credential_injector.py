"""Build isolated SSH and host-scoped HTTPS credential configuration.

Token values are deliberately resolved only by the short-lived Git credential-helper
process.  They are never interpolated into the Git command line.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .data_models import BotIdentity, HTTPSCredential


class CredentialError(RuntimeError):
    """Raised when a configured credential cannot be used safely."""


def _shell_quote(value: str) -> str:
    """Quote one value for the POSIX-like shell used by Git SSH/helper commands."""

    if value and all(character.isalnum() or character in "%+,-./:=@_" for character in value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def validate_ssh_key(key_path: str | os.PathLike[str]) -> Path:
    """Return an expanded, readable SSH private-key path or fail closed."""

    path = Path(key_path).expanduser()
    try:
        with path.open("rb"):
            pass
    except OSError as error:
        reason = error.strerror or type(error).__name__
        raise CredentialError(f"cannot read SSH key file {path}: {reason}") from error
    return path


def build_ssh_command(
    key_path: str | os.PathLike[str],
    strict_host_checking: bool = True,
    os_name: str | None = None,
) -> str:
    """Return an isolated ``GIT_SSH_COMMAND`` for one private key.

    Git for Windows evaluates this value in an MSYS shell, where backslashes are
    escape characters.  Normalizing the key path to forward slashes is safe on every
    supported platform and prevents paths such as ``C:\\keys\\bot_key`` from being
    corrupted.  ``-F`` prevents the operator's SSH config from selecting additional
    identities.
    """

    normalized_key = os.fspath(key_path).replace("\\", "/")
    null_device = "NUL" if (os.name if os_name is None else os_name) == "nt" else "/dev/null"
    strict_value = "accept-new" if strict_host_checking else "no"
    return " ".join(
        (
            "ssh",
            "-i",
            _shell_quote(normalized_key),
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            f"StrictHostKeyChecking={strict_value}",
            "-F",
            null_device,
        )
    )


def resolve_token(
    credential: HTTPSCredential,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    """Resolve and return an HTTPS token from its configured external source.

    Errors identify the failing source but never include command output or token
    contents.  The caller is responsible for keeping the returned value inside the
    credential-helper protocol rather than placing it in Git's argv.
    """

    environment = os.environ if env is None else env
    configured_sources = sum(
        source is not None
        for source in (
            credential.token_env_var,
            credential.token_file,
            credential.token_command,
        )
    )
    if configured_sources != 1:
        raise CredentialError("HTTPS credential must configure exactly one token source")

    if credential.token_env_var is not None:
        token = environment.get(credential.token_env_var, "")
        source = f"environment variable {credential.token_env_var}"
    elif credential.token_file is not None:
        token_path = credential.token_file.expanduser()
        source = f"token file {token_path}"
        try:
            token = token_path.read_text(encoding="utf-8")
        except OSError as error:
            reason = error.strerror or type(error).__name__
            raise CredentialError(f"cannot read {source}: {reason}") from error
    else:
        assert credential.token_command is not None
        source = "token command"
        try:
            proc = subprocess.run(  # noqa: S602 - explicit operator-owned command
                credential.token_command,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                env=dict(environment),
            )
        except OSError as error:
            raise CredentialError(f"cannot execute {source}: {type(error).__name__}") from error
        if proc.returncode != 0:
            raise CredentialError(f"{source} failed with exit code {proc.returncode}")
        token = proc.stdout

    token = token.strip()
    if not token:
        raise CredentialError(f"{source} did not provide a token")
    return token


def _credential_from_identity(identity: BotIdentity | HTTPSCredential) -> HTTPSCredential:
    if isinstance(identity, HTTPSCredential):
        return identity
    if identity.https is None:
        raise CredentialError(f"identity {identity.id!r} has no HTTPS credential")
    return identity.https


def _token_source_arguments(credential: HTTPSCredential) -> tuple[str, str]:
    if credential.token_env_var is not None:
        return "--token-env-var", credential.token_env_var
    if credential.token_file is not None:
        return "--token-file", str(credential.token_file).replace("\\", "/")
    if credential.token_command is not None:
        return "--token-command", credential.token_command
    raise CredentialError("HTTPS credential must configure exactly one token source")


def build_https_credential_flags(
    identity: BotIdentity | HTTPSCredential,
    host: str,
) -> list[str]:
    """Build host-scoped Git ``-c`` flags for an ephemeral credential helper.

    The helper command contains only non-secret source references.  It resolves the
    token after Git invokes it and returns the token over the credential protocol's
    stdout channel, keeping the secret out of argv, URLs, and stored configuration.
    """

    credential = _credential_from_identity(identity)
    source_option, source_reference = _token_source_arguments(credential)
    if not host or any(character.isspace() for character in host) or "/" in host:
        raise CredentialError("HTTPS credential host must be a non-empty host name")

    executable = sys.executable.replace("\\", "/")
    helper_parts = (
        executable,
        "-m",
        __name__,
        "--credential-helper",
        "--host",
        host,
        "--username",
        credential.username,
        source_option,
        source_reference,
    )
    helper = "!" + " ".join(_shell_quote(part) for part in helper_parts)
    scoped_key = f"credential.https://{host}.helper"
    return ["-c", f"{scoped_key}=", "-c", f"{scoped_key}={helper}"]

def _parse_helper_arguments(argv: Sequence[str]) -> tuple[str, str, HTTPSCredential, str]:
    if not argv or argv[0] != "--credential-helper":
        raise CredentialError("credential helper mode was not requested")

    values: dict[str, str] = {}
    index = 1
    while index + 1 < len(argv) and argv[index].startswith("--"):
        option = argv[index]
        if option in values:
            raise CredentialError(f"duplicate credential helper option: {option}")
        values[option] = argv[index + 1]
        index += 2
    if index != len(argv) - 1:
        raise CredentialError("invalid credential helper arguments")

    required = {"--host", "--username"}
    source_options = {"--token-env-var", "--token-file", "--token-command"}
    if not required <= values.keys() or len(source_options & values.keys()) != 1:
        raise CredentialError("incomplete credential helper arguments")
    unknown = values.keys() - required - source_options
    if unknown:
        raise CredentialError("unknown credential helper option")

    credential = HTTPSCredential(
        token_env_var=values.get("--token-env-var"),
        token_file=Path(values["--token-file"]) if "--token-file" in values else None,
        token_command=values.get("--token-command"),
        username=values["--username"],
    )
    return values["--host"], values["--username"], credential, argv[index]


def _read_credential_request() -> dict[str, str]:
    request: dict[str, str] = {}
    for raw_line in sys.stdin:
        line = raw_line.rstrip("\r\n")
        if not line:
            break
        key, separator, value = line.partition("=")
        if separator:
            request[key] = value
    return request


def _run_credential_helper(argv: Sequence[str]) -> int:
    host, username, credential, operation = _parse_helper_arguments(argv)
    request = _read_credential_request()
    if operation != "get":
        return 0
    if request.get("protocol") != "https" or request.get("host") != host:
        return 0

    token = resolve_token(credential)
    sys.stdout.write(f"username={username}\npassword={token}\n\n")
    sys.stdout.flush()
    return 0


def _main(argv: Sequence[str] | None = None) -> int:
    try:
        return _run_credential_helper(sys.argv[1:] if argv is None else argv)
    except CredentialError as error:
        sys.stderr.write(f"uv-shims credential helper: {error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
