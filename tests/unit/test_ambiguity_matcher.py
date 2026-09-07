"""Identity selection must refuse ambiguity independently of configuration order."""

from itertools import permutations

from uv_shims.git.data_models import BotIdentity
from uv_shims.git.repo_identity_matcher import match_identity


def identity(name, pattern):
    return BotIdentity(name, name, f"{name}@example.invalid", (pattern,))


def test_specificity_tie_refuses_instead_of_selecting_first_profile():
    profiles = (
        identity("organization", "github.com/acme/*"),
        identity("repository", "github.com/*/app"),
        identity("fallback", "github.com/*"),
    )
    for ordering in permutations(profiles):
        result = match_identity({"origin": "git@github.com:acme/app.git"}, ordering)
        assert result.identity is None
        assert result.is_ambiguous
        assert not result.is_conflict
        assert {candidate.id for candidate in result.candidates} == {"organization", "repository"}


def test_multi_remote_conflict_refuses_regardless_of_remote_and_profile_order():
    profiles = (
        identity("acme", "github.com/acme/*"),
        identity("personal", "gitlab.com/personal/*"),
    )
    remotes = (
        ("company", "git@github.com:acme/app.git"),
        ("fork", "https://gitlab.com/personal/app.git"),
    )
    for profile_order in permutations(profiles):
        for remote_order in permutations(remotes):
            result = match_identity(dict(remote_order), profile_order)
            assert result.identity is None
            assert result.is_conflict
            assert {candidate.id for candidate in result.candidates} == {"acme", "personal"}


def test_explicit_tracked_remote_resolves_otherwise_conflicting_remotes():
    acme = identity("acme", "github.com/acme/*")
    personal = identity("personal", "gitlab.com/personal/*")
    result = match_identity(
        {"origin": "git@github.com:acme/app.git", "fork": "https://gitlab.com/personal/app.git"},
        [acme, personal],
        "fork",
    )
    assert result.identity is personal
    assert not result.is_ambiguous
    assert not result.is_conflict
