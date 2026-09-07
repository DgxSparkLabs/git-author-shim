"""Unit tests for remote URL canonicalization and repo identity matching (T014).

Covers:
- SSH/HTTPS URL canonicalization (scp-like syntax, ssh:// with ports, userinfo
  stripping, ``.git`` suffix removal, tilde-user paths).
- Glob pattern matching (``host/org/repo``, ``host/org/*``, ``host/*``).
- Pattern specificity scoring (exact > org wildcard > host wildcard).
- Primary remote prioritization (tracked upstream, ``origin``, single remote).
- Tie-breaker refusal (equal-specificity matches and multi-remote conflicts).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from uv_shims.git.repo_identity_matcher import (
    CanonicalRepo,
    canonicalize_url,
    match_identity,
)


@dataclass(frozen=True)
class StubIdentity:
    """Minimal duck-typed stand-in for the real BotIdentity data model."""

    id: str
    match_patterns: tuple[str, ...]


# ---------------------------------------------------------------------------
# canonicalize_url: SSH forms
# ---------------------------------------------------------------------------


class TestCanonicalizeSsh:
    def test_scp_like_with_git_suffix(self) -> None:
        result = canonicalize_url("git@github.com:org/repo.git")
        assert result == CanonicalRepo(
            host="github.com", org_or_owner="org", repo="repo", port=None
        )

    def test_scp_like_without_git_suffix(self) -> None:
        result = canonicalize_url("git@github.com:org/repo")
        assert result == CanonicalRepo(
            host="github.com", org_or_owner="org", repo="repo", port=None
        )

    def test_ssh_url_with_explicit_port(self) -> None:
        result = canonicalize_url("ssh://git@github.com:22/org/repo.git")
        assert result == CanonicalRepo(host="github.com", org_or_owner="org", repo="repo", port=22)

    def test_ssh_url_with_tilde_user_path(self) -> None:
        result = canonicalize_url("ssh://git@git.example.com:2222/~user/repo")
        assert result == CanonicalRepo(
            host="git.example.com", org_or_owner="~user", repo="repo", port=2222
        )

    def test_ssh_url_without_port(self) -> None:
        result = canonicalize_url("ssh://git@github.com/org/repo.git")
        assert result == CanonicalRepo(
            host="github.com", org_or_owner="org", repo="repo", port=None
        )

    def test_host_is_lowercased(self) -> None:
        result = canonicalize_url("git@GitHub.COM:org/repo.git")
        assert result.host == "github.com"

    def test_nested_group_path_preserved(self) -> None:
        result = canonicalize_url("git@gitlab.com:org/subgroup/repo.git")
        assert result.org_or_owner == "org/subgroup"
        assert result.repo == "repo"


# ---------------------------------------------------------------------------
# canonicalize_url: HTTPS forms
# ---------------------------------------------------------------------------


class TestCanonicalizeHttps:
    def test_https_with_git_suffix(self) -> None:
        result = canonicalize_url("https://github.com/org/repo.git")
        assert result == CanonicalRepo(
            host="github.com", org_or_owner="org", repo="repo", port=None
        )

    def test_https_with_token_userinfo_no_suffix(self) -> None:
        result = canonicalize_url("https://token@github.com/org/repo")
        assert result == CanonicalRepo(
            host="github.com", org_or_owner="org", repo="repo", port=None
        )

    def test_https_with_explicit_port(self) -> None:
        result = canonicalize_url("https://git.example.com:8443/org/repo.git")
        assert result == CanonicalRepo(
            host="git.example.com", org_or_owner="org", repo="repo", port=8443
        )

    def test_https_trailing_slash(self) -> None:
        result = canonicalize_url("https://github.com/org/repo/")
        assert result.repo == "repo"
        assert result.org_or_owner == "org"

    def test_ssh_and_https_forms_canonicalize_identically(self) -> None:
        ssh = canonicalize_url("git@github.com:org/repo.git")
        https = canonicalize_url("https://github.com/org/repo.git")
        assert ssh.host == https.host
        assert ssh.org_or_owner == https.org_or_owner
        assert ssh.repo == https.repo


# ---------------------------------------------------------------------------
# canonicalize_url: canonical string + invalid input
# ---------------------------------------------------------------------------


class TestCanonicalForm:
    def test_canonical_string(self) -> None:
        result = canonicalize_url("git@github.com:org/repo.git")
        assert result.canonical == "github.com/org/repo"

    @pytest.mark.parametrize(
        "bad_url",
        [
            "",
            "   ",
            "not-a-url",
            "https://github.com",
            "https://github.com/repo",
            "git@github.com:",
        ],
    )
    def test_invalid_urls_raise_value_error(self, bad_url: str) -> None:
        with pytest.raises(ValueError):
            canonicalize_url(bad_url)


# ---------------------------------------------------------------------------
# Glob pattern matching (single remote, single identity)
# ---------------------------------------------------------------------------


class TestPatternMatching:
    def test_exact_match(self) -> None:
        identity = StubIdentity("exact", ("github.com/org/repo",))
        result = match_identity({"origin": "git@github.com:org/repo.git"}, [identity])
        assert result.identity is identity
        assert not result.is_conflict
        assert not result.is_ambiguous

    def test_org_wildcard_match(self) -> None:
        identity = StubIdentity("org-wild", ("github.com/org/*",))
        result = match_identity({"origin": "https://github.com/org/anything.git"}, [identity])
        assert result.identity is identity

    def test_host_wildcard_match(self) -> None:
        identity = StubIdentity("host-wild", ("github.com/*",))
        result = match_identity({"origin": "git@github.com:any-org/any-repo.git"}, [identity])
        assert result.identity is identity

    def test_host_wildcard_matches_nested_groups(self) -> None:
        identity = StubIdentity("host-wild", ("gitlab.com/*",))
        result = match_identity({"origin": "git@gitlab.com:org/subgroup/repo.git"}, [identity])
        assert result.identity is identity

    def test_non_matching_pattern_returns_no_identity(self) -> None:
        identity = StubIdentity("other", ("gitlab.com/org/*",))
        result = match_identity({"origin": "git@github.com:org/repo.git"}, [identity])
        assert result.identity is None
        assert not result.is_conflict
        assert not result.is_ambiguous
        assert result.candidates == ()

    def test_no_remotes_returns_no_identity(self) -> None:
        identity = StubIdentity("exact", ("github.com/org/repo",))
        result = match_identity({}, [identity])
        assert result.identity is None
        assert not result.is_conflict
        assert not result.is_ambiguous


# ---------------------------------------------------------------------------
# Specificity scoring: exact > org wildcard > host wildcard
# ---------------------------------------------------------------------------


class TestSpecificityScoring:
    def test_exact_beats_org_wildcard(self) -> None:
        exact = StubIdentity("exact", ("github.com/org/repo",))
        org_wild = StubIdentity("org-wild", ("github.com/org/*",))
        result = match_identity({"origin": "git@github.com:org/repo.git"}, [org_wild, exact])
        assert result.identity is exact

    def test_org_wildcard_beats_host_wildcard(self) -> None:
        org_wild = StubIdentity("org-wild", ("github.com/org/*",))
        host_wild = StubIdentity("host-wild", ("github.com/*",))
        result = match_identity({"origin": "git@github.com:org/repo.git"}, [host_wild, org_wild])
        assert result.identity is org_wild

    def test_exact_beats_host_wildcard(self) -> None:
        exact = StubIdentity("exact", ("github.com/org/repo",))
        host_wild = StubIdentity("host-wild", ("github.com/*",))
        result = match_identity({"origin": "git@github.com:org/repo.git"}, [host_wild, exact])
        assert result.identity is exact

    def test_most_specific_pattern_within_single_identity_wins(self) -> None:
        """An identity with several patterns is scored by its best match."""
        identity = StubIdentity("multi", ("github.com/*", "github.com/org/repo"))
        other = StubIdentity("other", ("github.com/org/*",))
        result = match_identity({"origin": "git@github.com:org/repo.git"}, [other, identity])
        assert result.identity is identity


# ---------------------------------------------------------------------------
# Tie-breaker refusal: equal specificity -> ambiguous
# ---------------------------------------------------------------------------


class TestAmbiguityRefusal:
    def test_identical_patterns_tie_is_ambiguous(self) -> None:
        first = StubIdentity("first", ("github.com/org/*",))
        second = StubIdentity("second", ("github.com/org/*",))
        result = match_identity({"origin": "git@github.com:org/repo.git"}, [first, second])
        assert result.identity is None
        assert result.is_ambiguous
        assert not result.is_conflict
        assert {c.id for c in result.candidates} == {"first", "second"}

    def test_equal_specificity_different_patterns_tie(self) -> None:
        first = StubIdentity("first", ("github.com/org/*",))
        second = StubIdentity("second", ("github.com/*/repo",))
        result = match_identity({"origin": "git@github.com:org/repo.git"}, [first, second])
        assert result.identity is None
        assert result.is_ambiguous
        assert {c.id for c in result.candidates} == {"first", "second"}

    def test_less_specific_loser_not_listed_as_candidate(self) -> None:
        first = StubIdentity("first", ("github.com/org/*",))
        second = StubIdentity("second", ("github.com/*/repo",))
        loser = StubIdentity("loser", ("github.com/*",))
        result = match_identity({"origin": "git@github.com:org/repo.git"}, [loser, first, second])
        assert result.is_ambiguous
        assert {c.id for c in result.candidates} == {"first", "second"}


# ---------------------------------------------------------------------------
# Primary remote prioritization
# ---------------------------------------------------------------------------


class TestPrimaryRemote:
    def test_explicit_primary_remote_wins_over_origin(self) -> None:
        work = StubIdentity("work", ("github.com/work-org/*",))
        personal = StubIdentity("personal", ("github.com/personal/*",))
        remotes = {
            "origin": "git@github.com:personal/repo.git",
            "upstream": "git@github.com:work-org/repo.git",
        }
        result = match_identity(remotes, [work, personal], primary_remote="upstream")
        assert result.identity is work
        assert not result.is_conflict

    def test_origin_is_default_primary(self) -> None:
        work = StubIdentity("work", ("github.com/work-org/*",))
        personal = StubIdentity("personal", ("github.com/personal/*",))
        remotes = {
            "origin": "git@github.com:work-org/repo.git",
            "fork": "git@github.com:personal/repo.git",
        }
        result = match_identity(remotes, [work, personal])
        assert result.identity is work
        assert not result.is_conflict

    def test_single_remote_is_primary(self) -> None:
        identity = StubIdentity("only", ("gitlab.com/org/*",))
        result = match_identity({"upstream": "git@gitlab.com:org/repo.git"}, [identity])
        assert result.identity is identity

    def test_primary_remote_matching_nothing_yields_no_identity(self) -> None:
        identity = StubIdentity("work", ("github.com/work-org/*",))
        remotes = {
            "origin": "git@github.com:other-org/repo.git",
            "upstream": "git@github.com:work-org/repo.git",
        }
        # origin is the default primary and matches nothing -> no identity,
        # even though a non-primary remote would have matched.
        result = match_identity(remotes, [identity])
        assert result.identity is None
        assert not result.is_conflict

    def test_unparseable_primary_url_yields_no_identity(self) -> None:
        identity = StubIdentity("work", ("github.com/work-org/*",))
        result = match_identity({"origin": "not-a-url"}, [identity])
        assert result.identity is None
        assert not result.is_conflict


# ---------------------------------------------------------------------------
# Multi-remote conflict without a primary remote
# ---------------------------------------------------------------------------


class TestMultiRemoteConflict:
    def test_conflicting_identities_without_primary_is_conflict(self) -> None:
        work = StubIdentity("work", ("github.com/work-org/*",))
        personal = StubIdentity("personal", ("gitlab.com/personal/*",))
        remotes = {
            "fork": "git@github.com:work-org/repo.git",
            "mirror": "git@gitlab.com:personal/repo.git",
        }
        result = match_identity(remotes, [work, personal])
        assert result.identity is None
        assert result.is_conflict
        assert not result.is_ambiguous
        assert {c.id for c in result.candidates} == {"work", "personal"}

    def test_same_identity_across_remotes_is_not_conflict(self) -> None:
        identity = StubIdentity("work", ("github.com/work-org/*", "gitlab.com/work-org/*"))
        remotes = {
            "fork": "git@github.com:work-org/repo.git",
            "mirror": "git@gitlab.com:work-org/repo.git",
        }
        result = match_identity(remotes, [identity])
        assert result.identity is identity
        assert not result.is_conflict

    def test_unmatched_secondary_remote_does_not_conflict(self) -> None:
        work = StubIdentity("work", ("github.com/work-org/*",))
        remotes = {
            "fork": "git@github.com:work-org/repo.git",
            "mirror": "git@unmatched.example.com:org/repo.git",
        }
        result = match_identity(remotes, [work])
        assert result.identity is work
        assert not result.is_conflict

    def test_explicit_primary_remote_overrides_potential_conflict(self) -> None:
        work = StubIdentity("work", ("github.com/work-org/*",))
        personal = StubIdentity("personal", ("gitlab.com/personal/*",))
        remotes = {
            "fork": "git@github.com:work-org/repo.git",
            "mirror": "git@gitlab.com:personal/repo.git",
        }
        result = match_identity(remotes, [work, personal], primary_remote="fork")
        assert result.identity is work
        assert not result.is_conflict
