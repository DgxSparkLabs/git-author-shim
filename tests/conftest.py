"""Shared pytest harness for ``git-author-shim``.

Fixtures exported here:

``clean_env``
    Autouse environment sanitizer. Removes every ambient ``GIT_*``, ``CLAUDE_*``,
    ``UV_SHIM_*`` / ``__UV_SHIM_*`` variable plus known agent markers so no test ever
    observes the developer's real shell.
``isolated_env``
    Function-scoped fake ``HOME`` / ``USERPROFILE`` / ``XDG_CONFIG_HOME`` / ``APPDATA``
    rooted in ``tmp_path``, with helpers for writing shim config files.
``fake_git`` / ``fake_git_factory``
    Recording fake ``git`` executable. Every invocation appends argv, stdin, env and
    cwd to a JSONL log; exit code, stdout and stderr are test-controlled.
``temp_repo``
    Factory creating real repositories via ``git init`` inside ``tmp_path``.
``real_git()``
    Module-level helper resolving a genuine ``git`` binary (never this project's own
    ``git`` console script), used by ``temp_repo`` and available to tests.

All fixtures are function-scoped: nothing leaks between tests.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

# Allow ``import git_author_shim`` without an installed/editable wheel. Single bootstrap for
# the whole suite; do not duplicate this in individual test modules.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# ``PATH`` as it looked before any fixture mutated it, so ``temp_repo`` still finds the
# genuine binary while ``fake_git`` shadows ``git``.
_IMPORT_PATH: str = os.environ.get("PATH", "")


@functools.cache
def real_git() -> str | None:
    """Absolute path to a genuine ``git`` binary, or ``None`` if there is none.

    Deliberately *not* a plain ``shutil.which("git")``: this project installs its own
    ``git`` console script into the environment's scripts directory, which would
    otherwise make every repository fixture recurse into the shim under test. Candidates
    inside the interpreter's prefixes are skipped and the winner must answer
    ``git --version``.
    """
    excluded: list[Path] = []
    for prefix in (sys.prefix, sys.base_prefix, sys.exec_prefix):
        try:
            excluded.append(Path(prefix).resolve())
        except OSError:  # pragma: no cover - exotic filesystem
            continue

    for entry in _IMPORT_PATH.split(os.pathsep):
        if not entry:
            continue
        try:
            directory = Path(entry).resolve()
        except OSError:
            continue
        if any(directory == ex or ex in directory.parents for ex in excluded):
            continue
        candidate = shutil.which("git", path=str(directory))
        if candidate is None:
            continue
        try:
            probe = subprocess.run(  # noqa: S603
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and probe.stdout.startswith("git version"):
            return candidate
    return None


#: Environment variables wiped by name.
SANITIZED_NAMES: frozenset[str] = frozenset(
    {
        "AGENT_ID",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "CODEX_SANDBOX",
        "CURSOR_AGENT",
        "OPENAI_AGENT",
        "EMAIL",
        "XDG_CONFIG_HOME",
    }
)

#: Environment variables wiped by prefix.
SANITIZED_PREFIXES: tuple[str, ...] = ("GIT_", "CLAUDE_", "UV_SHIM_", "__UV_SHIM_")


def _sanitized(names: Iterable[str]) -> list[str]:
    return [
        name for name in names if name in SANITIZED_NAMES or name.startswith(SANITIZED_PREFIXES)
    ]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe ambient Git/agent/shim environment variables for the duration of a test."""
    for name in _sanitized(list(os.environ)):
        monkeypatch.delenv(name, raising=False)
    # Keep child Git processes from ever blocking on interactive credential prompts.
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")


@dataclass(frozen=True, slots=True)
class IsolatedEnv:
    """Filesystem locations of the fake user profile installed for one test."""

    home: Path
    xdg_config_home: Path
    appdata: Path
    monkeypatch: pytest.MonkeyPatch

    @property
    def shim_config_dir(self) -> Path:
        """Directory holding ``config.toml`` (``~/.git-shim``)."""
        return self.home / ".git-shim"

    @property
    def config_path(self) -> Path:
        """Default global config path (``~/.git-shim/config.toml``)."""
        return self.shim_config_dir / "config.toml"

    def write_config(self, content: str, *, name: str = "config.toml") -> Path:
        """Write a global shim config file and return its path."""
        target = self.shim_config_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def setenv(self, name: str, value: str) -> None:
        self.monkeypatch.setenv(name, value)

    def delenv(self, name: str) -> None:
        self.monkeypatch.delenv(name, raising=False)


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> IsolatedEnv:
    """Point every home-directory lookup at a throwaway profile under ``tmp_path``."""
    home = tmp_path / "home"
    xdg = home / ".config"
    appdata = home / "AppData" / "Roaming"
    for directory in (home, xdg, appdata):
        directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    # ``Path.home()`` consults these first on both platforms; also reset the expanduser
    # cache users of ``os.path.expanduser`` rely on.
    monkeypatch.setenv("HOMEDRIVE", "")
    monkeypatch.setenv("HOMEPATH", "")
    monkeypatch.chdir(tmp_path)

    return IsolatedEnv(home=home, xdg_config_home=xdg, appdata=appdata, monkeypatch=monkeypatch)


# --------------------------------------------------------------------------------------
# Recording fake ``git``
# --------------------------------------------------------------------------------------

_RECORDER_SOURCE = r'''
"""Recording stand-in for the real git binary (written by tests/conftest.py)."""
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

record = {
    "program": sys.argv[0],
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "env": dict(os.environ),
    "stdin": "",
}
try:
    if not sys.stdin.isatty():
        record["stdin"] = sys.stdin.read()
except (OSError, ValueError):
    pass

with (BASE / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\n")

for stream, filename in ((sys.stdout, "stdout.txt"), (sys.stderr, "stderr.txt")):
    payload = BASE / filename
    if payload.exists():
        stream.write(payload.read_text(encoding="utf-8"))
        stream.flush()

code_file = BASE / "exit_code.txt"
sys.exit(int(code_file.read_text(encoding="utf-8").strip()) if code_file.exists() else 0)
'''


@dataclass(frozen=True, slots=True)
class GitInvocation:
    """One recorded call into the fake ``git``."""

    program: str
    argv: list[str]
    cwd: str
    env: dict[str, str]
    stdin: str

    @property
    def command(self) -> str | None:
        """First non-option argument, e.g. ``commit`` in ``git -c x=y commit``."""
        skip_value = False
        for arg in self.argv:
            if skip_value:
                skip_value = False
                continue
            if arg in ("-c", "-C", "--git-dir", "--work-tree", "--namespace"):
                skip_value = True
                continue
            if arg.startswith("-"):
                continue
            return arg
        return None


@dataclass(frozen=True, slots=True)
class FakeGit:
    """Handle for a recording fake ``git`` executable on disk."""

    path: Path
    bin_dir: Path
    state_dir: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def calls(self) -> list[GitInvocation]:
        log = self.state_dir / "calls.jsonl"
        if not log.exists():
            return []
        return [
            GitInvocation(
                program=entry["program"],
                argv=list(entry["argv"]),
                cwd=entry["cwd"],
                env=dict(entry["env"]),
                stdin=entry["stdin"],
            )
            for entry in (
                json.loads(line)
                for line in log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        ]

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_call(self) -> GitInvocation:
        calls = self.calls
        if not calls:
            raise AssertionError(f"fake git at {self.path} was never invoked")
        return calls[-1]

    def set_exit_code(self, code: int) -> None:
        (self.state_dir / "exit_code.txt").write_text(str(code), encoding="utf-8")

    def set_stdout(self, text: str) -> None:
        (self.state_dir / "stdout.txt").write_text(text, encoding="utf-8")

    def set_stderr(self, text: str) -> None:
        (self.state_dir / "stderr.txt").write_text(text, encoding="utf-8")

    def reset(self) -> None:
        for name in ("calls.jsonl", "stdout.txt", "stderr.txt", "exit_code.txt"):
            (self.state_dir / name).unlink(missing_ok=True)

    def run(
        self,
        *args: str,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
        cwd: Path | str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Invoke the fake directly; handy for asserting the recording works."""
        return subprocess.run(  # noqa: S603
            [str(self.path), *args],
            input=stdin if stdin is not None else "",
            capture_output=True,
            text=True,
            env=dict(env) if env is not None else None,
            cwd=str(cwd) if cwd is not None else None,
            check=False,
        )


def _write_fake_git(root: Path, *, stem: str) -> FakeGit:
    root.mkdir(parents=True, exist_ok=True)
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    recorder = root / "_recorder.py"
    recorder.write_text(_RECORDER_SOURCE, encoding="utf-8")

    if sys.platform == "win32":
        # ``.cmd`` is in the default ``PATHEXT``; CreateProcess dispatches it via cmd.exe.
        launcher = bin_dir / f"{stem}.cmd"
        launcher.write_text(
            f'@echo off\r\n"{sys.executable}" "{recorder}" %*\r\nexit /b %ERRORLEVEL%\r\n',
            encoding="utf-8",
        )
    else:
        launcher = bin_dir / stem
        launcher.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{recorder}" "$@"\n', encoding="utf-8"
        )
        launcher.chmod(0o755)

    return FakeGit(path=launcher, bin_dir=bin_dir, state_dir=root)


@pytest.fixture
def fake_git_factory(tmp_path: Path) -> Callable[..., FakeGit]:
    """Create additional recording fakes, e.g. a decoy shim earlier on ``PATH``."""
    created: dict[str, FakeGit] = {}

    def factory(name: str = "git", *, dirname: str | None = None) -> FakeGit:
        stem = Path(name).stem or name
        root = tmp_path / (dirname or f"fake-{stem}-{len(created)}")
        fake = _write_fake_git(root, stem=stem)
        created[str(fake.path)] = fake
        return fake

    return factory


@pytest.fixture
def fake_git(fake_git_factory: Callable[..., FakeGit], monkeypatch: pytest.MonkeyPatch) -> FakeGit:
    """A recording fake ``git`` prepended to ``PATH`` (and to ``PATHEXT`` on Windows)."""
    fake = fake_git_factory("git", dirname="fake-git")
    monkeypatch.setenv("PATH", str(fake.bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    if sys.platform == "win32":
        pathext = os.environ.get("PATHEXT", "")
        if ".CMD" not in pathext.upper().split(os.pathsep):
            monkeypatch.setenv("PATHEXT", ".CMD" + os.pathsep + pathext)
    return fake


# --------------------------------------------------------------------------------------
# Real temporary repositories
# --------------------------------------------------------------------------------------

_GIT_ENV_BASE: dict[str, str] = {
    "GIT_AUTHOR_NAME": "Harness Author",
    "GIT_AUTHOR_EMAIL": "harness-author@example.invalid",
    "GIT_COMMITTER_NAME": "Harness Committer",
    "GIT_COMMITTER_EMAIL": "harness-committer@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
}


@dataclass(frozen=True, slots=True)
class TempRepo:
    """A real Git working tree created for one test."""

    path: Path
    git_env: dict[str, str]
    git_binary: str

    def __fspath__(self) -> str:
        return str(self.path)

    @property
    def git_dir(self) -> Path:
        return self.path / ".git"

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run the *real* git binary inside this repository."""
        return subprocess.run(  # noqa: S603
            [self.git_binary, *args],
            cwd=str(self.path),
            env=self.git_env,
            capture_output=True,
            text=True,
            check=check,
        )

    def config(self, key: str, value: str) -> None:
        self.git("config", key, value)

    def add_remote(self, name: str, url: str) -> None:
        self.git("remote", "add", name, url)

    def set_upstream(self, remote: str, *, branch: str | None = None) -> None:
        """Wire ``branch.<name>.remote``/``.merge`` without touching the network."""
        local = branch or self.current_branch
        self.git("update-ref", f"refs/remotes/{remote}/{local}", "HEAD")
        self.config(f"branch.{local}.remote", remote)
        self.config(f"branch.{local}.merge", f"refs/heads/{local}")

    @property
    def current_branch(self) -> str:
        return self.git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def commit(self, message: str = "work", *, allow_empty: bool = True) -> str:
        args = ["commit", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        self.git(*args)
        return self.git("rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def temp_repo(tmp_path: Path) -> Callable[..., TempRepo]:
    """Factory creating real repositories with ``git init`` under ``tmp_path``."""
    git_binary = real_git()
    if git_binary is None:
        pytest.skip("no genuine git binary found on PATH")

    counter = {"n": 0}

    def factory(
        name: str | None = None,
        *,
        remotes: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
        branch: str = "main",
        initial_commit: bool = True,
        upstream: str | None = None,
        bare: bool = False,
        home: Path | None = None,
    ) -> TempRepo:
        counter["n"] += 1
        repo_path = tmp_path / (name or f"repo{counter['n']}")
        repo_path.mkdir(parents=True, exist_ok=True)

        fake_home = home or (tmp_path / "git-home")
        fake_home.mkdir(parents=True, exist_ok=True)
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            **_GIT_ENV_BASE,
            "HOME": str(fake_home),
            "USERPROFILE": str(fake_home),
            "GIT_CONFIG_GLOBAL": str(fake_home / ".gitconfig-harness"),
        }

        init_args = ["init", "-b", branch]
        if bare:
            init_args.append("--bare")
        subprocess.run(  # noqa: S603
            [git_binary, *init_args],
            cwd=str(repo_path),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

        repo = TempRepo(path=repo_path, git_env=env, git_binary=git_binary)
        items = remotes.items() if isinstance(remotes, Mapping) else list(remotes or ())
        for remote_name, url in items:
            repo.add_remote(remote_name, url)
        if initial_commit and not bare:
            repo.commit("initial")
        if upstream is not None:
            repo.set_upstream(upstream, branch=branch)
        return repo

    return factory
