"""Inspection contracts: documented JSON, secret-free plans, and real dry runs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from uv_shims.git.cli import main, run_git

_CONFIG = """[[identities]]
id = "acme"
name = "Acme Bot"
email = "bot@acme.invalid"
match_patterns = ["github.com/acme/*", "gitlab.com/acme/*"]
[identities.https]
token_env_var = "BOT_TOKEN"
"""
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "specs/001-git-author-shim/contracts/cli.md"


def assert_schema(value, schema):
    """Check the type, enum, required and nested properties in the published schema."""
    types = {"object": dict, "string": str, "boolean": bool, "null": type(None)}
    expected = schema.get("type")
    if expected is not None:
        names = [expected] if isinstance(expected, str) else expected
        assert type(value) in tuple(types[name] for name in names)
    if "enum" in schema:
        assert value in schema["enum"]
    if isinstance(value, dict):
        assert set(schema.get("required", ())) <= value.keys()
        for name, field in schema.get("properties", {}).items():
            if name in value:
                assert_schema(value[name], field)


@pytest.mark.parametrize(
    "mode,command", [("agent", "push"), ("agent", "status"), ("human", "commit")]
)
def test_explain_json_matches_published_schema_without_token_characters(
    isolated_env, temp_repo, monkeypatch, capsys, mode, command
):
    isolated_env.write_config(_CONFIG)
    # Each canary character is absent from ordinary JSON fields. Checking the
    # decoded output also catches escaped or partially disclosed token material.
    secret = "£¤¥¦§©«¬®°±µ¶"
    monkeypatch.setenv("BOT_TOKEN", secret)
    monkeypatch.setenv("UV_SHIM_GIT_MODE", mode)
    repo = temp_repo(remotes={"origin": f"https://{secret}@github.com/acme/app.git"})
    monkeypatch.chdir(repo.path)
    before = repo.git("show-ref").stdout

    assert main(["explain", "--json", command]) == 0

    output = capsys.readouterr()
    plan = json.loads(output.out)
    schema = json.loads(
        _SCHEMA_PATH.read_text(encoding="utf-8").split("```json\n")[1].split("```", 1)[0]
    )
    assert_schema(plan, schema)
    decoded = json.dumps(plan, ensure_ascii=False) + output.err
    assert set(secret).isdisjoint(decoded)
    assert plan["mode"] == mode
    assert plan["is_write"] is (command != "status")
    assert plan["write_permitted"] is True
    if mode == "agent":
        assert plan["repository_canonical_url"] == "github.com/acme/app"
        assert plan["https_token_source"] == "env:BOT_TOKEN"
    assert repo.git("show-ref").stdout == before


def test_explain_refusal_is_inspectable_and_never_runs_git(
    isolated_env, temp_repo, fake_git, monkeypatch, capsys
):
    repo = temp_repo(remotes={"origin": "git@github.com:unconfigured/app.git"})
    monkeypatch.chdir(repo.path)
    monkeypatch.setenv("UV_SHIM_GIT_MODE", "agent")

    assert main(["explain", "--json", "push"]) == 0

    plan = json.loads(capsys.readouterr().out)
    assert plan["write_permitted"] is False
    assert "github.com/unconfigured/app" in plan["failure_reason"]
    assert fake_git.calls == []


@pytest.mark.parametrize("mode", ["human", "agent"])
def test_explain_environment_is_dry_run_even_for_explicit_human_mode(
    isolated_env, fake_git, monkeypatch, capsys, mode
):
    monkeypatch.setenv("UV_SHIM_GIT_MODE", mode)
    monkeypatch.setenv("UV_SHIM_GIT_EXPLAIN", "1")

    assert run_git(["push"]) == 0

    assert "Mode:" in capsys.readouterr().out
    assert fake_git.calls == []


def test_list_identities_renders_one_tabular_row_per_profile(isolated_env, capsys):
    isolated_env.write_config(
        _CONFIG
        + """
[[identities]]
id = "other"
name = "Other Bot"
email = "other@acme.invalid"
match_patterns = ["example.com/team/*"]
"""
    )

    assert main(["list-identities"]) == 0

    rows = [line.split("\t") for line in capsys.readouterr().out.splitlines()]
    assert rows == [
        ["acme", "Acme Bot <bot@acme.invalid>", "github.com/acme/*, gitlab.com/acme/*"],
        ["other", "Other Bot <other@acme.invalid>", "example.com/team/*"],
    ]


def test_explain_never_executes_token_command(
    isolated_env, temp_repo, tmp_path, monkeypatch, capsys
):
    marker = tmp_path / "token-command-ran"
    script = tmp_path / "token_source.py"
    script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\nprint('secret-token')\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{script}"'
    isolated_env.write_config(
        _CONFIG.replace('token_env_var = "BOT_TOKEN"', f"token_command = {json.dumps(command)}")
    )
    repo = temp_repo(remotes={"origin": "https://github.com/acme/app.git"})
    monkeypatch.chdir(repo.path)
    monkeypatch.setenv("UV_SHIM_GIT_MODE", "agent")

    assert main(["explain", "--json", "push"]) == 0

    plan = json.loads(capsys.readouterr().out)
    assert plan["https_token_source"] == "command"
    assert plan["write_permitted"] is True
    assert not marker.exists()


def test_explain_invalid_remote_does_not_disclose_embedded_credentials(
    isolated_env, temp_repo, monkeypatch, capsys
):
    secret = "£¤¥¦§©«¬®°±µ¶"
    repo = temp_repo(remotes={"origin": f"https://{secret}@github.com/incomplete"})
    monkeypatch.chdir(repo.path)
    monkeypatch.setenv("UV_SHIM_GIT_MODE", "agent")

    assert main(["explain", "--json", "push"]) == 0

    output = capsys.readouterr()
    plan = json.loads(output.out)
    assert plan["write_permitted"] is False
    assert set(secret).isdisjoint(json.dumps(plan, ensure_ascii=False) + output.err)


def test_explain_missing_ssh_key_does_not_preflight_credentials(
    isolated_env, temp_repo, fake_git, monkeypatch, capsys
):
    isolated_env.write_config(
        _CONFIG.split("[identities.https]", 1)[0]
        + """
[identities.ssh]
key_file = "~/.ssh/not-provisioned-yet"
"""
    )
    repo = temp_repo(remotes={"origin": "git@github.com:acme/app.git"})
    monkeypatch.chdir(repo.path)
    monkeypatch.setenv("UV_SHIM_GIT_MODE", "agent")

    assert main(["explain", "--json", "push"]) == 0

    plan = json.loads(capsys.readouterr().out)
    assert plan["write_permitted"] is True
    assert fake_git.calls == []
