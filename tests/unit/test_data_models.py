from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from git_author_shim.data_models import (
    BotIdentity,
    CommitClass,
    HTTPSCredential,
    IdentityMode,
    InvocationPlan,
    SSHCredential,
)


def test_identity_mode_values_and_string_conversion() -> None:
    assert [mode.value for mode in IdentityMode] == ["auto", "agent", "human"]
    assert str(IdentityMode.AUTO) == "auto"
    assert IdentityMode("agent") is IdentityMode.AGENT
    assert IdentityMode("human") is IdentityMode.HUMAN


def test_commit_class_values_and_string_conversion() -> None:
    assert [commit_class.value for commit_class in CommitClass] == [
        "originating",
        "carrying",
    ]
    assert str(CommitClass.ORIGINATING) == "originating"
    assert CommitClass("carrying") is CommitClass.CARRYING


def test_ssh_credential_is_immutable_and_defaults_to_strict_host_checking() -> None:
    credential = SSHCredential(key_file=Path("~/.ssh/agent_ed25519"))

    assert credential.key_file == Path("~/.ssh/agent_ed25519")
    assert credential.strict_host_checking is True
    with pytest.raises(FrozenInstanceError):
        credential.strict_host_checking = False  # type: ignore[misc]


def test_https_credential_describes_a_secret_source_without_storing_a_token() -> None:
    credential = HTTPSCredential(
        token_env_var="BOT_TOKEN",
        token_file=None,
        token_command=None,
    )

    assert credential.token_env_var == "BOT_TOKEN"
    assert credential.token_file is None
    assert credential.token_command is None
    assert credential.username == "x-access-token"
    assert "actual-token-value" not in repr(credential)


def test_bot_identity_uses_immutable_match_patterns_and_credentials() -> None:
    ssh = SSHCredential(Path("keys/bot"), strict_host_checking=False)
    https = HTTPSCredential(token_file=Path("secrets/token"), username="oauth2")
    identity = BotIdentity(
        id="acme-bot",
        name="Acme Bot",
        email="bot@acme.test",
        match_patterns=("github.com/acme/*", "gitlab.com/acme/service"),
        ssh=ssh,
        https=https,
    )

    assert identity.match_patterns == (
        "github.com/acme/*",
        "gitlab.com/acme/service",
    )
    assert identity.ssh is ssh
    assert identity.https is https
    with pytest.raises(FrozenInstanceError):
        identity.name = "Other"  # type: ignore[misc]


def test_invocation_plan_captures_the_resolved_decision() -> None:
    identity = BotIdentity(
        id="acme-bot",
        name="Acme Bot",
        email="bot@acme.test",
        match_patterns=("github.com/acme/*",),
    )
    plan = InvocationPlan(
        mode=IdentityMode.AGENT,
        is_write=True,
        matched_identity=identity,
        commit_class=CommitClass.ORIGINATING,
        author=("Acme Bot", "bot@acme.test"),
        committer=("Acme Bot", "bot@acme.test"),
        target_host="github.com",
        transport="ssh",
        credential_source="key:~/.ssh/agent_ed25519",
    )

    assert plan.mode is IdentityMode.AGENT
    assert plan.matched_identity is identity
    assert plan.author == ("Acme Bot", "bot@acme.test")
    assert plan.committer == ("Acme Bot", "bot@acme.test")
    assert plan.fail_closed is False
    assert plan.failure_reason is None


def test_invocation_plan_repr_and_string_redact_every_secret_substring() -> None:
    token = "ghp_super-secret-token_123"
    shorter_secret = "secret-token"
    plan = InvocationPlan(
        mode=IdentityMode.AGENT,
        is_write=True,
        credential_source=f"env:BOT_TOKEN resolved={token}",
        failure_reason=f"credential {shorter_secret} rejected",
        secret_tokens=(token, shorter_secret),
    )

    for rendered in (repr(plan), str(plan), f"{plan}"):
        assert token not in rendered
        assert shorter_secret not in rendered
        assert "[REDACTED]" in rendered


def test_invocation_plan_is_immutable() -> None:
    plan = InvocationPlan(mode=IdentityMode.HUMAN, is_write=False)

    with pytest.raises(FrozenInstanceError):
        plan.is_write = True  # type: ignore[misc]
