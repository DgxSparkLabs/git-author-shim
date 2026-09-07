"""End-to-end proof that *real* agent-harness markers drive the shim.

Every other integration module forces ``GIT_SHIM_MODE=agent``; that shortcut skips
the detector entirely. These tests instead set the environment variables an actual
harness exports (``AGENT_ID``, ``CLAUDE_CODE``, ... and the ``PI_*`` variables the
live OMP/Orca harness injects) and assert the whole chain end to end:

    marker -> IdentityMode.AGENT -> matched identity -> stamped Git object.

Nothing here needs a credential, a network socket, or the operator's real profile:
``isolated_env`` relocates ``HOME``, ``temp_repo`` builds a local repository, and
the only remote URLs used are unreachable ``test-org`` placeholders.

Inspection uses ``git_author_shim.cli:main`` — the ``git-shim`` console-script
entry point. ``python -m git_author_shim`` is the *git trampoline* and would
forward ``explain`` to real Git.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from git_author_shim.agent_detection import _VENDOR_MARKERS
from git_author_shim.cli import main, run_git

_SRC = Path(__file__).resolve().parents[2] / "src"

#: Ambient process environment captured at import time, *before* the autouse
#: ``clean_env`` fixture sanitizes anything. Used only to probe the harness this
#: suite happens to be running under; never fed to a child process wholesale.
_AMBIENT: dict[str, str] = dict(os.environ)

#: Names a live OMP/Orca/Claude Code process actually exports. None of these are
#: in ``_VENDOR_MARKERS`` (which looks for ``CLAUDE_CODE`` / ``AGENT_ID``, not
#: ``CLAUDECODE`` / ``ORCA_*``), so operators must list them under
#: ``settings.custom_agent_markers``. Names only — never capture token values.
_LIVE_CUSTOM_MARKERS = (
    "CLAUDECODE",
    "OMPCODE",
    "ORCA_WORKTREE_ID",
    "ORCA_TAB_ID",
    "ORCA_WORKSPACE_ID",
    "PI_TOOL_BRIDGE_SESSION",
    "PI_SESSION_FILE",
    "PI_ARTIFACTS_DIR",
)

_IDENTITY_ID = "test-org-bot"
_BOT_NAME = "Test Org Bot"
_BOT_EMAIL = "bot@test-org.invalid"
_BOT = f"{_BOT_NAME} <{_BOT_EMAIL}>"
_BOTH = f"{_BOT}|{_BOT}"

_BASE_CONFIG = f"""[[identities]]
id = "{_IDENTITY_ID}"
name = "{_BOT_NAME}"
email = "{_BOT_EMAIL}"
match_patterns = ["github.com/test-org/*"]
"""


def _config(*, custom_markers: tuple[str, ...] = (), ssh_key: Path | None = None) -> str:
    """Build a global ``config.toml`` body; settings must precede the identity array."""
    head = ""
    if custom_markers:
        head = "[settings]\ncustom_agent_markers = " + json.dumps(list(custom_markers)) + "\n\n"
    tail = ""
    if ssh_key is not None:
        tail = "\n[identities.ssh]\nkey_file = " + json.dumps(str(ssh_key)) + "\n"
    return head + _BASE_CONFIG + tail


def _shim_env(real_git: str, **markers: str) -> dict[str, str]:
    """Child environment for a subprocess *git trampoline* run.

    Deliberately sets no ``GIT_SHIM_MODE``: detection must come from ``markers``.
    ``os.environ`` has already been scrubbed of every agent/Git variable by the
    autouse ``clean_env`` fixture.
    """
    existing = os.environ.get("PYTHONPATH")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_SRC) + (os.pathsep + existing if existing else "")
    env["GIT_SHIM_SHADOW"] = "1"
    env["GIT_SHIM_REAL_PATH"] = real_git
    env.update(markers)
    return env


def _run_shim(repo, real_git: str, *args: str, **markers: str) -> subprocess.CompletedProcess[str]:
    """Invoke the shadowed-git trampoline (``python -m git_author_shim``)."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "git_author_shim", *args],
        cwd=repo.path,
        env=_shim_env(real_git, **markers),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _explain(capsys, *git_args: str) -> dict:
    """Run ``git-shim explain --json`` in-process (the operator CLI entry point)."""
    code = main(["explain", "--json", *git_args])
    output = capsys.readouterr()
    assert code == 0, output.err
    return json.loads(output.out)


@pytest.fixture(autouse=True)
def _wipe_live_harness_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """``clean_env`` only strips ``CLAUDE_*`` / ``AGENT_ID``; live flags differ."""
    for name in _LIVE_CUSTOM_MARKERS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def agent_repo(isolated_env, temp_repo, monkeypatch):
    """A local repository whose ``origin`` matches the configured bot identity."""
    isolated_env.write_config(_BASE_CONFIG)
    repo = temp_repo(remotes={"origin": "git@github.com:test-org/repo.git"})
    monkeypatch.chdir(repo.path)
    monkeypatch.setenv("GIT_SHIM_REAL_PATH", repo.git_binary)
    # A human identity in the ambient environment: the shim must override it, not defer.
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Human Operator")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "human@example.invalid")
    return repo


# --------------------------------------------------------------------------------------
# Harness integrity: without this the agent/human tests below can silently false-pass
# --------------------------------------------------------------------------------------


def test_vendor_marker_tuple_matches_the_published_contract() -> None:
    """A renamed or dropped vendor marker must fail this suite, not silently skip."""
    assert _VENDOR_MARKERS == (
        "AGENT_ID",
        "CLAUDE_CODE",
        "CLAUDE_AGENT",
        "CODEX_SANDBOX",
        "CURSOR_AGENT",
        "OPENAI_AGENT",
    )


def test_no_vendor_marker_leaks_from_the_host_harness() -> None:
    """This suite frequently runs *inside* an agent; a leak would forge every result."""
    assert [marker for marker in _VENDOR_MARKERS if marker in os.environ] == []
    assert "GIT_SHIM_MODE" not in os.environ


# --------------------------------------------------------------------------------------
# Scenario 1: zero-execution inspection
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("marker", _VENDOR_MARKERS)
def test_each_vendor_marker_resolves_agent_mode_without_running_git(
    agent_repo, fake_git, monkeypatch, capsys, marker
) -> None:
    monkeypatch.setenv(marker, "1")

    plan = _explain(capsys, "commit", "-m", "work")

    assert plan["mode"] == "agent"
    assert plan["detected_marker"] == marker
    assert plan["matched_identity_id"] == _IDENTITY_ID
    assert plan["author"] == {"name": _BOT_NAME, "email": _BOT_EMAIL}
    assert plan["committer"] == {"name": _BOT_NAME, "email": _BOT_EMAIL}
    assert plan["repository_canonical_url"] == "github.com/test-org/repo"
    assert plan["transport"] == "ssh"
    # ``explain`` is a pure inspection: no Git process, therefore no credential use.
    assert fake_git.call_count == 0


def test_marker_presence_alone_is_sufficient_even_when_its_value_is_empty(
    agent_repo, fake_git, monkeypatch, capsys
) -> None:
    """Harnesses export flag-style markers; an empty value must not read as absent."""
    monkeypatch.setenv("CLAUDE_CODE", "")

    plan = _explain(capsys, "commit")

    assert (plan["mode"], plan["detected_marker"]) == ("agent", "CLAUDE_CODE")
    assert fake_git.call_count == 0


@pytest.mark.parametrize("marker", _LIVE_CUSTOM_MARKERS)
def test_real_harness_variable_is_detected_through_custom_agent_markers(
    isolated_env, agent_repo, fake_git, monkeypatch, capsys, marker
) -> None:
    """Live OMP/Claude flags are not vendor markers; custom markers are the hook."""
    isolated_env.write_config(_config(custom_markers=(marker,)))
    monkeypatch.setenv(marker, "1")

    plan = _explain(capsys, "commit")

    assert plan["mode"] == "agent"
    assert plan["detected_marker"] == marker
    assert plan["matched_identity_id"] == _IDENTITY_ID
    assert fake_git.call_count == 0


def test_live_harness_environment_is_detected_when_configured(
    isolated_env, agent_repo, fake_git, monkeypatch, capsys
) -> None:
    """Probe the *actual* harness this suite runs under, using its real values.

    Token-bearing ``ORCA_AGENT_HOOK_*`` / ``PI_TOOL_BRIDGE_TOKEN`` names are
    intentionally excluded: presence of a workspace/tab id is enough.
    """
    live = {
        name: _AMBIENT[name]
        for name in (*_VENDOR_MARKERS, *_LIVE_CUSTOM_MARKERS)
        if name in _AMBIENT
    }
    if not live:
        pytest.skip("not running inside a recognized agent harness")
    isolated_env.write_config(_config(custom_markers=_LIVE_CUSTOM_MARKERS))
    for name, value in live.items():
        monkeypatch.setenv(name, value)

    plan = _explain(capsys, "commit")

    assert plan["mode"] == "agent"
    assert plan["detected_marker"] in {*_VENDOR_MARKERS, *_LIVE_CUSTOM_MARKERS}
    assert plan["matched_identity_id"] == _IDENTITY_ID
    assert fake_git.call_count == 0


# --------------------------------------------------------------------------------------
# Scenario 2: local commit authorship, 100% offline
# --------------------------------------------------------------------------------------


def test_marker_driven_commit_is_stamped_with_the_bot_and_leaves_gitconfig_alone(
    isolated_env, agent_repo, monkeypatch
) -> None:
    monkeypatch.setenv("AGENT_ID", "orca-worktree-42")
    (agent_repo.path / "work.txt").write_text("agent output\n", encoding="utf-8")

    assert run_git(["add", "work.txt"]) == 0
    assert run_git(["commit", "-m", "agent test commit"]) == 0

    assert agent_repo.git("log", "-1", "--format=%an <%ae>|%cn <%ce>").stdout.strip() == _BOTH
    assert agent_repo.git("log", "-1", "--format=%s").stdout.strip() == "agent test commit"
    # The operator's identity files were never created, let alone written to.
    assert not (isolated_env.home / ".gitconfig").exists()
    assert not (isolated_env.home / ".ssh").exists()


# --------------------------------------------------------------------------------------
# Scenario 3: secondary Git objects
# --------------------------------------------------------------------------------------


def test_marker_driven_tag_records_the_bot_as_tagger(agent_repo, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE", "1")
    tagged = agent_repo.git("cat-file", "commit", "HEAD").stdout

    assert run_git(["tag", "-a", "v1.0.0", "-m", "Release"]) == 0

    assert (
        agent_repo.git(
            "for-each-ref", "--format=%(taggername) <%(taggeremail:trim)>", "refs/tags/v1.0.0"
        ).stdout.strip()
        == _BOT
    )
    assert agent_repo.git("cat-file", "commit", "v1.0.0^{}").stdout == tagged


def test_marker_driven_stash_attributes_every_generated_commit(agent_repo, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_ID", "orca-worktree-42")
    tracked = agent_repo.path / "tracked.txt"
    tracked.write_text("base\n", encoding="utf-8")
    agent_repo.git("add", "tracked.txt")
    agent_repo.commit("tracked base")
    tracked.write_text("staged\n", encoding="utf-8")
    agent_repo.git("add", "tracked.txt")
    tracked.write_text("unstaged\n", encoding="utf-8")

    assert run_git(["stash", "push", "-m", "agent work"]) == 0

    for revision in ("refs/stash", "refs/stash^2"):
        assert (
            agent_repo.git("show", "-s", "--format=%an <%ae>|%cn <%ce>", revision).stdout.strip()
            == _BOTH
        )


def test_marker_driven_notes_commit_is_attributed_to_the_bot(agent_repo, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_AGENT", "1")
    original = agent_repo.git("cat-file", "commit", "HEAD").stdout

    assert run_git(["notes", "add", "-m", "Note", "HEAD"]) == 0

    assert (
        agent_repo.git(
            "show", "-s", "--format=%an <%ae>|%cn <%ce>", "refs/notes/commits"
        ).stdout.strip()
        == _BOTH
    )
    assert agent_repo.git("cat-file", "commit", "HEAD").stdout == original


# --------------------------------------------------------------------------------------
# Scenario 4: fail-closed credential pre-flight, zero network egress
# --------------------------------------------------------------------------------------


def test_marker_driven_push_aborts_before_any_network_connection(
    isolated_env, agent_repo, fake_git, tmp_path
) -> None:
    missing_key = tmp_path / "nonexistent" / "bot_key"
    isolated_env.write_config(_config(ssh_key=missing_key))

    result = _run_shim(
        agent_repo, str(fake_git.path), "push", "origin", "main", AGENT_ID="orca-worktree-42"
    )

    assert result.returncode == 1
    assert "bot_key" in result.stderr
    assert "SSH key" in result.stderr
    # Neither Git nor SSH ever started: the refusal happens strictly pre-flight.
    assert fake_git.call_count == 0


# --------------------------------------------------------------------------------------
# Scenario 5: human control baselines
# --------------------------------------------------------------------------------------


def test_explicit_human_override_beats_every_marker(
    agent_repo, fake_git, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("GIT_SHIM_MODE", "human")
    for marker in _VENDOR_MARKERS:
        monkeypatch.setenv(marker, "1")

    plan = _explain(capsys, "commit")

    assert plan["mode"] == "human"
    assert plan["detected_marker"] is None
    assert plan["matched_identity_id"] is None
    assert plan["author"] == {}
    assert plan["committer"] == {}
    assert fake_git.call_count == 0


def test_absent_markers_resolve_to_human_and_leave_git_untouched(agent_repo, capsys) -> None:
    plan = _explain(capsys, "commit")
    assert (plan["mode"], plan["detected_marker"]) == ("human", None)

    (agent_repo.path / "human.txt").write_text("hand written\n", encoding="utf-8")
    assert run_git(["add", "human.txt"]) == 0
    assert run_git(["commit", "-m", "human commit"]) == 0

    assert (
        agent_repo.git("log", "-1", "--format=%an <%ae>|%cn <%ce>").stdout.strip()
        == "Human Operator <human@example.invalid>|Human Operator <human@example.invalid>"
    )
