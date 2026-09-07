"""Integration tests for zero-mutation human passthrough (T022).

When no agent marker is present the shim must behave like a thin wrapper: the
operator keeps their own identity, and the files that define it -- ``~/.gitconfig``
and ``~/.ssh/config`` -- must be byte-for-byte identical before and after the
shim runs. Equality is asserted on SHA-256 digests rather than on mtimes so a
rewrite with identical content would still be caught by a hash of the whole
tracked set.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"

_MATCHING_CONFIG = """[[identities]]
id = "acme"
name = "Acme Bot"
email = "bot@acme.invalid"
match_patterns = ["github.com/acme/*"]

[identities.ssh]
key_file = "~/.ssh/acme_bot_ed25519"
"""


def shim_env(**overrides: str | None) -> dict[str, str]:
    """Copy the (already sanitized) test environment for a shim subprocess."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + existing if existing else "")
    env["GIT_SHIM_SHADOW"] = "1"
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
) -> subprocess.CompletedProcess[str]:
    """Run the ``git`` shim entry point in a real child process."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "git_author_shim", *args],
        input="",
        capture_output=True,
        text=True,
        env=shim_env() if env is None else env,
        cwd=None if cwd is None else str(cwd),
        check=False,
        timeout=120,
    )


def digests(paths: list[Path]) -> dict[str, str]:
    """SHA-256 of every tracked path, keyed by path (missing files included)."""
    return {
        str(path): (hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "<absent>")
        for path in paths
    }


def operator_profile(isolated_env) -> list[Path]:
    """Populate a realistic operator profile and return the tracked paths."""
    gitconfig = isolated_env.home / ".gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = Operator\n\temail = operator@example.invalid\n[core]\n\teditor = vim\n",
        encoding="utf-8",
    )
    ssh_dir = isolated_env.home / ".ssh"
    ssh_dir.mkdir(parents=True, exist_ok=True)
    ssh_config = ssh_dir / "config"
    ssh_config.write_text(
        "Host github.com\n  User git\n  IdentityFile ~/.ssh/id_ed25519\n",
        encoding="utf-8",
    )
    known_hosts = ssh_dir / "known_hosts"
    known_hosts.write_text("github.com ssh-ed25519 AAAA\n", encoding="utf-8")
    return [gitconfig, ssh_config, known_hosts]


def test_human_mode_leaves_operator_files_byte_for_byte_identical(
    isolated_env, fake_git, temp_repo
):
    tracked = operator_profile(isolated_env)
    tracked.append(isolated_env.write_config(_MATCHING_CONFIG))
    repo = temp_repo("operator-repo", remotes={"origin": "git@github.com:acme/app.git"})
    before = digests(tracked)

    for argv in (("commit", "-m", "operator work"), ("push", "origin", "main")):
        result = run_shim(*argv, cwd=repo.path)
        assert result.returncode == 0, result.stderr

    assert digests(tracked) == before


def test_human_mode_injects_no_identity_or_credentials(isolated_env, fake_git, temp_repo):
    operator_profile(isolated_env)
    isolated_env.write_config(_MATCHING_CONFIG)
    repo = temp_repo("operator-repo", remotes={"origin": "git@github.com:acme/app.git"})

    result = run_shim("commit", "-m", "operator work", cwd=repo.path)

    assert result.returncode == 0, result.stderr
    call = fake_git.last_call
    assert call.argv == ["commit", "-m", "operator work"]
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_SSH_COMMAND",
    ):
        assert name not in call.env


def test_explicit_human_override_ignores_agent_markers(isolated_env, fake_git, temp_repo):
    tracked = operator_profile(isolated_env)
    tracked.append(isolated_env.write_config(_MATCHING_CONFIG))
    repo = temp_repo("operator-repo", remotes={"origin": "git@github.com:acme/app.git"})
    before = digests(tracked)

    result = run_shim(
        "commit",
        "-m",
        "operator work",
        env=shim_env(AGENT_ID="agent-worker-9", GIT_SHIM_MODE="human"),
        cwd=repo.path,
    )

    assert result.returncode == 0, result.stderr
    assert "GIT_AUTHOR_NAME" not in fake_git.last_call.env
    assert digests(tracked) == before


def test_explicit_human_override_never_reads_the_shim_configuration(isolated_env, fake_git):
    isolated_env.write_config("this is not valid TOML = = =\n")

    result = run_shim("status", env=shim_env(GIT_SHIM_MODE="human"))

    assert result.returncode == 0, result.stderr
    assert fake_git.last_call.argv == ["status"]


def test_human_mode_commit_records_the_operator_identity(isolated_env, temp_repo):
    repo = temp_repo("operator-identity")
    repo.config("user.name", "Operator")
    repo.config("user.email", "operator@example.invalid")
    env = shim_env(
        GIT_SHIM_REAL_PATH=repo.git_binary,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=str(isolated_env.home / ".gitconfig-absent"),
    )

    result = run_shim("commit", "--allow-empty", "-m", "operator work", env=env, cwd=repo.path)

    assert result.returncode == 0, result.stderr
    recorded = subprocess.run(  # noqa: S603
        [repo.git_binary, "log", "-1", "--format=%an <%ae>|%cn <%ce>"],
        cwd=str(repo.path),
        env=repo.git_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert recorded == ("Operator <operator@example.invalid>|Operator <operator@example.invalid>")


def test_human_mode_forwards_unmanaged_flags_and_environment(fake_git):
    argv = ["-c", "color.ui=always", "diff", "--stat", "--", "src/file with space.py"]

    result = run_shim(*argv, env=shim_env(OPERATOR_ONLY_VAR="visible"))

    assert result.returncode == 0, result.stderr
    call = fake_git.last_call
    assert call.argv == argv
    assert call.env["OPERATOR_ONLY_VAR"] == "visible"
