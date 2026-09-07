"""Remote URL canonicalization and bot identity matching (T015).

Normalizes configured Git remote URLs into canonical ``(host, org, repo)``
tuples and matches them against identity glob patterns
(``host/org/repo``, ``host/org/*``, ``host/*``).

Primary remote policy (research.md Decision 4): local writes match against the
current branch's tracked upstream remote, or ``origin``, or the single
configured remote. If multiple remotes resolve to conflicting identities
without a primary remote, matching fails closed (``is_conflict``). Specificity
ties between identities fail closed as well (``is_ambiguous``, US10).

Identities are duck-typed: any object exposing ``id`` and ``match_patterns``
attributes (or a mapping with those keys) is accepted, keeping this module
decoupled from the data-model layer.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import urlsplit

__all__ = ["CanonicalRepo", "MatchResult", "canonicalize_url", "match_identity"]


@dataclass(frozen=True)
class CanonicalRepo:
    """Canonical form of a Git remote URL."""

    host: str
    org_or_owner: str
    repo: str
    port: int | None = None

    @property
    def canonical(self) -> str:
        """Canonical ``host/org/repo`` string used for pattern matching."""
        return f"{self.host}/{self.org_or_owner}/{self.repo}"


@dataclass(frozen=True)
class MatchResult:
    """Outcome of matching remotes against configured identities.

    ``identity`` is the winning identity, or ``None`` when there is no match
    or matching failed closed. ``is_ambiguous`` marks an equal-specificity tie
    between identities; ``is_conflict`` marks multiple remotes resolving to
    different identities without a primary remote. ``candidates`` names the
    identities involved in a tie or conflict.
    """

    identity: Any | None = None
    is_conflict: bool = False
    is_ambiguous: bool = False
    candidates: tuple[Any, ...] = ()


# scp-like SSH syntax: [user@]host:path  (e.g. git@github.com:org/repo.git)
_SCP_LIKE_RE = re.compile(r"^(?:[^@/:]+@)?(?P<host>[^/:]+):(?P<path>[^:].*)$")


def canonicalize_url(url_str: str) -> CanonicalRepo:
    """Normalize a Git remote URL into a :class:`CanonicalRepo`.

    Handles scp-like SSH (``git@host:org/repo.git``), ``ssh://`` URLs with
    optional ports and tilde-user paths, and HTTP(S) URLs with optional
    userinfo and ports. The host is lowercased and a trailing ``.git`` suffix
    on the repository name is stripped.

    Raises:
        ValueError: If the URL is empty, has no host, or its path does not
            contain at least an owner and repository segment.
    """
    if not url_str or not url_str.strip():
        raise ValueError("remote URL is empty")
    url_str = url_str.strip()

    port: int | None = None
    if "://" in url_str:
        parts = urlsplit(url_str)
        host = parts.hostname or ""
        port = parts.port  # raises ValueError on a malformed port
        path = parts.path
    else:
        match = _SCP_LIKE_RE.match(url_str)
        if match is None:
            raise ValueError(f"unrecognized remote URL: {url_str!r}")
        host = match.group("host")
        path = match.group("path")

    host = host.lower()
    if not host:
        raise ValueError(f"remote URL has no host: {url_str!r}")

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        raise ValueError(f"remote URL path needs at least owner/repo segments: {url_str!r}")
    repo = segments[-1]
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    org_or_owner = "/".join(segments[:-1])
    if not repo or not org_or_owner:
        raise ValueError(f"remote URL has empty owner or repo: {url_str!r}")

    return CanonicalRepo(host=host, org_or_owner=org_or_owner, repo=repo, port=port)


def _identity_key(identity: Any) -> Any:
    if isinstance(identity, Mapping):
        return identity.get("id", id(identity))
    return getattr(identity, "id", id(identity))


def _identity_patterns(identity: Any) -> Iterable[str]:
    if isinstance(identity, Mapping):
        return identity.get("match_patterns", ())
    return getattr(identity, "match_patterns", ())


def _pattern_specificity(pattern: str) -> int:
    """Score a pattern by its number of literal (non-``*``) segments."""
    return sum(1 for segment in pattern.split("/") if segment != "*")


def _best_score(identity: Any, canonical: str) -> int | None:
    """Best specificity score among an identity's patterns, or None."""
    scores = [
        _pattern_specificity(pattern)
        for pattern in _identity_patterns(identity)
        if fnmatchcase(canonical, pattern)
    ]
    return max(scores) if scores else None


def _resolve_single(canonical: CanonicalRepo, identities: list[Any]) -> MatchResult:
    """Match one canonical repo against identities; ties are ambiguous."""
    scored: list[tuple[int, Any]] = []
    for identity in identities:
        score = _best_score(identity, canonical.canonical)
        if score is not None:
            scored.append((score, identity))
    if not scored:
        return MatchResult()
    top = max(score for score, _ in scored)
    winners = tuple(identity for score, identity in scored if score == top)
    if len(winners) > 1:
        return MatchResult(is_ambiguous=True, candidates=winners)
    return MatchResult(identity=winners[0])


def match_identity(
    remotes: Mapping[str, str],
    identities: Iterable[Any],
    primary_remote: str | None = None,
) -> MatchResult:
    """Resolve the bot identity for a repository's remotes.

    Args:
        remotes: Mapping of remote name to remote URL.
        identities: Candidate identities (duck-typed ``id``/``match_patterns``).
        primary_remote: Name of the current branch's tracked upstream remote,
            if known. Falls back to ``origin``, then to a single configured
            remote.

    Returns:
        A :class:`MatchResult`. Matching fails closed (``identity is None``)
        with ``is_ambiguous`` on equal-specificity ties and ``is_conflict``
        when remotes resolve to conflicting identities without a primary
        remote.
    """
    identity_list = list(identities)

    canonical_remotes: dict[str, CanonicalRepo] = {}
    for name, url in remotes.items():
        try:
            canonical_remotes[name] = canonicalize_url(url)
        except ValueError:
            continue  # unparseable remotes cannot claim an identity
    if not canonical_remotes:
        return MatchResult()

    primary: str | None = None
    if primary_remote is not None and primary_remote in canonical_remotes:
        primary = primary_remote
    elif "origin" in canonical_remotes:
        primary = "origin"
    elif len(canonical_remotes) == 1:
        primary = next(iter(canonical_remotes))

    if primary is not None:
        return _resolve_single(canonical_remotes[primary], identity_list)

    # No primary remote: every remote must agree on the same identity.
    winners: dict[Any, Any] = {}
    for canonical in canonical_remotes.values():
        result = _resolve_single(canonical, identity_list)
        if result.is_ambiguous:
            return result
        if result.identity is not None:
            winners.setdefault(_identity_key(result.identity), result.identity)

    if len(winners) > 1:
        return MatchResult(is_conflict=True, candidates=tuple(winners.values()))
    if winners:
        return MatchResult(identity=next(iter(winners.values())))
    return MatchResult()
