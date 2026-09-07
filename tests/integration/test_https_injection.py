"""Integration tests for host-scoped HTTPS credential injection (T026/T027).

The proof here is behavioural rather than textual: a real Git runs ``git credential
fill`` through the shim, so what is asserted is the credential Git actually hands to
a transport. That is the only way to show that an untrusted helper recorded in
``.git/config`` is genuinely neutralized (Git's empty-value reset semantics) and that
helpers for other hosts keep working untouched.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"

_REMOTE = "https://github.com/acme/app.git"
_SCOPED_KEY = "credential.https://github.com.helper"
_FOREIGN_KEY = "credential.https://gitlab.com.helper"

_HTTPS_CONFIG = """[[identities]]
id = "acme"
name = "Acme Bot"
email = "bot@acme.invalid"
match_patterns = ["github.com/acme/*"]

[identities.https]
{source}
username = "acme-bot"
"""

_FAKE_HELPER = """import sys

for line in sys.stdin:
    if not line.strip():
        break
sys.stdout.write("username=operator\\npassword=" + sys.argv[1] + "\\n\\n")
"""


def shim_env(**overrides: str | None) -> dict[str, str]:
    """Copy the (already sanitized) test environment for a shim subprocess."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + existing if existing else "")
    for name, value in overrides.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return env


def run_shim(
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | str | None = None,
    stdin: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run the ``git`` shim entry point in a real child process."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "git_author_shim", *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=shim_env() if env is None else env,
        cwd=None if cwd is None else str(cwd),
        check=False,
        timeout=120,
    )


def agent_env(isolated_env, **overrides: str | None) -> dict[str, str]:
    """Environment of an agent-driven invocation with no ambient Git identity."""
    return shim_env(
        AGENT_ID="agent-worker-1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(isolated_env.home / ".gitconfig-absent"),
        GIT_TERMINAL_PROMPT="0",
        **overrides,
    )


def fake_helper(tmp_path: Path, name: str, token: str) -> str:
    """A ``.git/config``-style helper command answering with a fixed token.

    Git evaluates ``!`` helpers through a POSIX shell on every platform, so the
    command is quoted with POSIX rules even on Windows.
    """
    script = tmp_path / f"{name}.py"
    script.write_text(_FAKE_HELPER, encoding="utf-8")
    parts = (sys.executable, str(script), token)
    return "!" + " ".join(shlex.quote(part.replace("\\", "/")) for part in parts)


def credential_fill(repo, env: dict[str, str], host: str = "github.com") -> dict[str, str]:
    """Ask the shim to fill a credential and parse Git's key/value response."""
    result = run_shim(
        "credential",
        "fill",
        env=env,
        cwd=repo.path,
        stdin=f"protocol=https\nhost={host}\n\n",
    )
    assert result.returncode == 0, result.stderr
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def test_matched_host_gets_a_scoped_reset_and_helper_pair(isolated_env, fake_git, temp_repo):
    isolated_env.write_config(_HTTPS_CONFIG.format(source='token_env_var = "ACME_BOT_TOKEN"'))
    repo = temp_repo("acme-app", remotes={"origin": _REMOTE})

    result = run_shim(
        "push",
        "origin",
        "main",
        env=agent_env(isolated_env, ACME_BOT_TOKEN="bot-secret"),
        cwd=repo.path,
    )

    assert result.returncode == 0, result.stderr
    argv = fake_git.last_call.argv
    assert argv[:3] == ["-c", f"{_SCOPED_KEY}=", "-c"]
    assert argv[3].startswith(f"{_SCOPED_KEY}=!")
    assert argv[4:] == ["push", "origin", "main"]
    # Nothing global: only the matched host's helper list is ever rewritten.
    assert not any(argument.startswith("credential.helper") for argument in argv)


def test_bot_token_never_reaches_git_arguments_or_the_helper_reference(
    isolated_env, fake_git, temp_repo
):
    secret = "ghp-do-not-leak-this-value"
    isolated_env.write_config(_HTTPS_CONFIG.format(source='token_env_var = "ACME_BOT_TOKEN"'))
    repo = temp_repo("acme-app", remotes={"origin": _REMOTE})

    result = run_shim(
        "push", "origin", "main", env=agent_env(isolated_env, ACME_BOT_TOKEN=secret), cwd=repo.path
    )

    assert result.returncode == 0, result.stderr
    argv = fake_git.last_call.argv
    assert secret not in " ".join(argv)
    assert "--token-env-var ACME_BOT_TOKEN" in argv[3]


@pytest.mark.parametrize("source_kind", ["env", "file", "command"])
def test_bot_token_is_delivered_for_the_matched_host(
    isolated_env, temp_repo, tmp_path, source_kind
):
    token = f"{source_kind}-secret"
    overrides: dict[str, str | None] = {}
    if source_kind == "env":
        source = 'token_env_var = "ACME_BOT_TOKEN"'
        overrides["ACME_BOT_TOKEN"] = token
    elif source_kind == "file":
        token_file = tmp_path / "tokens" / "acme.txt"
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(token + "\n", encoding="utf-8")
        source = f'token_file = "{str(token_file).replace(os.sep, "/")}"'
    else:
        source = f'token_command = "echo {token}"'

    isolated_env.write_config(_HTTPS_CONFIG.format(source=source))
    repo = temp_repo("acme-app", remotes={"origin": _REMOTE})
    env = agent_env(isolated_env, UV_SHIM_GIT_REAL_PATH=repo.git_binary, **overrides)

    filled = credential_fill(repo, env)

    assert filled["username"] == "acme-bot"
    assert filled["password"] == token


def test_untrusted_repository_helper_is_neutralized(isolated_env, temp_repo, tmp_path):
    isolated_env.write_config(_HTTPS_CONFIG.format(source='token_env_var = "ACME_BOT_TOKEN"'))
    repo = temp_repo("acme-app", remotes={"origin": _REMOTE})
    repo.config(_SCOPED_KEY, fake_helper(tmp_path, "untrusted", "REPO-PLANTED-TOKEN"))
    env = agent_env(
        isolated_env,
        UV_SHIM_GIT_REAL_PATH=repo.git_binary,
        ACME_BOT_TOKEN="bot-secret",
    )

    filled = credential_fill(repo, env)

    assert filled["password"] == "bot-secret"
    assert filled["username"] == "acme-bot"


def test_foreign_host_credentials_remain_untouched(isolated_env, temp_repo, tmp_path):
    isolated_env.write_config(_HTTPS_CONFIG.format(source='token_env_var = "ACME_BOT_TOKEN"'))
    repo = temp_repo("acme-app", remotes={"origin": _REMOTE})
    repo.config(_FOREIGN_KEY, fake_helper(tmp_path, "foreign", "OPERATOR-TOKEN"))
    env = agent_env(
        isolated_env,
        UV_SHIM_GIT_REAL_PATH=repo.git_binary,
        ACME_BOT_TOKEN="bot-secret",
    )

    filled = credential_fill(repo, env, host="gitlab.com")

    assert filled["password"] == "OPERATOR-TOKEN"
    assert filled["username"] == "operator"


def test_unmatched_repository_receives_no_credential_flags(isolated_env, fake_git, temp_repo):
    isolated_env.write_config(_HTTPS_CONFIG.format(source='token_env_var = "ACME_BOT_TOKEN"'))
    repo = temp_repo("other-app", remotes={"origin": "https://gitlab.com/someone/app.git"})

    result = run_shim("fetch", "origin", env=agent_env(isolated_env), cwd=repo.path)

    assert result.returncode == 0, result.stderr
    assert fake_git.last_call.argv == ["fetch", "origin"]
