"""Immutable data structures used by the Git identity shim."""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class IdentityMode(StrEnum):
    """Controls whether an invocation uses an agent or human identity."""

    AUTO = "auto"
    AGENT = "agent"
    HUMAN = "human"


class CommitClass(StrEnum):
    """Describes how a commit-producing operation treats authorship."""

    ORIGINATING = "originating"
    CARRYING = "carrying"


@dataclass(frozen=True, slots=True)
class SSHCredential:
    """A reference to an SSH private key; no key material is stored here."""

    key_file: Path
    strict_host_checking: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "key_file", Path(self.key_file))


@dataclass(frozen=True, slots=True)
class HTTPSCredential:
    """References one external source for an HTTPS token."""

    token_env_var: str | None = None
    token_file: Path | None = None
    token_command: str | None = None
    username: str = "x-access-token"

    def __post_init__(self) -> None:
        if self.token_file is not None:
            object.__setattr__(self, "token_file", Path(self.token_file))


@dataclass(frozen=True, slots=True)
class BotIdentity:
    """Commit identity and host-scoped credential references for an agent."""

    id: str
    name: str
    email: str
    match_patterns: tuple[str, ...]
    ssh: SSHCredential | None = None
    https: HTTPSCredential | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "match_patterns", tuple(self.match_patterns))


@dataclass(frozen=True, slots=True)
class GlobalSettings:
    """Global activation and agent-marker detection settings."""

    default_mode: IdentityMode = IdentityMode.AUTO
    vendor_detection: bool = True
    custom_agent_markers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "default_mode", IdentityMode(self.default_mode))
        object.__setattr__(
            self,
            "custom_agent_markers",
            tuple(self.custom_agent_markers),
        )


@dataclass(frozen=True, slots=True)
class ShimConfig:
    """Validated global shim configuration."""

    settings: GlobalSettings = field(default_factory=GlobalSettings)
    identities: tuple[BotIdentity, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "identities", tuple(self.identities))


@dataclass(frozen=True, slots=True)
class InvocationPlan:
    """A resolved, inspectable decision for one Git invocation.

    ``secret_tokens`` is a defensive redaction list for values that were observed
    while resolving credentials. It is excluded from equality and never rendered.
    Runtime execution should still avoid putting token values in a plan at all.
    """

    mode: IdentityMode
    is_write: bool
    matched_identity: BotIdentity | None = None
    commit_class: CommitClass | None = None
    author: tuple[str, str] | None = None
    committer: tuple[str, str] | None = None
    target_host: str | None = None
    transport: str | None = None
    credential_source: str | None = None
    fail_closed: bool = False
    failure_reason: str | None = None
    secret_tokens: tuple[str, ...] = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", IdentityMode(self.mode))
        if self.commit_class is not None:
            object.__setattr__(self, "commit_class", CommitClass(self.commit_class))
        if self.author is not None:
            object.__setattr__(self, "author", tuple(self.author))
        if self.committer is not None:
            object.__setattr__(self, "committer", tuple(self.committer))
        object.__setattr__(self, "secret_tokens", tuple(self.secret_tokens))

    def __repr__(self) -> str:
        rendered = (
            f"{type(self).__name__}("
            f"mode={self.mode!r}, "
            f"is_write={self.is_write!r}, "
            f"matched_identity={self.matched_identity!r}, "
            f"commit_class={self.commit_class!r}, "
            f"author={self.author!r}, "
            f"committer={self.committer!r}, "
            f"target_host={self.target_host!r}, "
            f"transport={self.transport!r}, "
            f"credential_source={self.credential_source!r}, "
            f"fail_closed={self.fail_closed!r}, "
            f"failure_reason={self.failure_reason!r})"
        )
        redacted_tokens = sorted(
            (token for token in self.secret_tokens if token),
            key=len,
            reverse=True,
        )
        for token in redacted_tokens:
            rendered = rendered.replace(token, "[REDACTED]")
        return rendered

    def __str__(self) -> str:
        return repr(self)
