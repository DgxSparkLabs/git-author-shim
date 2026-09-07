"""Mode precedence and marker detection without exposing marker values."""

import pytest

from git_author_shim.agent_detection import resolve_identity_mode
from git_author_shim.data_models import GlobalSettings, IdentityMode, ShimConfig


def configured(**settings):
    return ShimConfig(settings=GlobalSettings(**settings))


def test_agent_override_forces_agent_without_markers():
    config = configured(default_mode=IdentityMode.HUMAN)
    assert resolve_identity_mode(config, {"UV_SHIM_GIT_MODE": "agent"}) == (
        IdentityMode.AGENT,
        None,
    )


def test_human_override_wins_over_agent_configuration_and_markers():
    config = configured(default_mode=IdentityMode.AGENT)
    env = {"UV_SHIM_GIT_MODE": "human", "AGENT_ID": "worker"}
    assert resolve_identity_mode(config, env) == (IdentityMode.HUMAN, None)


@pytest.mark.parametrize(
    "marker",
    ["AGENT_ID", "CLAUDE_CODE", "CLAUDE_AGENT", "CODEX_SANDBOX", "CURSOR_AGENT", "OPENAI_AGENT"],
)
def test_auto_detects_each_supported_vendor_marker(marker):
    assert resolve_identity_mode(configured(), {marker: "private-agent-value"}) == (
        IdentityMode.AGENT,
        marker,
    )


def test_marker_presence_including_empty_value_activates_agent():
    assert resolve_identity_mode(configured(), {"AGENT_ID": ""}) == (
        IdentityMode.AGENT,
        "AGENT_ID",
    )


def test_auto_override_reevaluates_instead_of_using_configured_mode():
    config = configured(default_mode=IdentityMode.AGENT)
    assert resolve_identity_mode(config, {"UV_SHIM_GIT_MODE": "auto"}) == (
        IdentityMode.HUMAN,
        None,
    )
    human_config = configured(default_mode=IdentityMode.HUMAN)
    assert resolve_identity_mode(human_config, {"UV_SHIM_GIT_MODE": "auto", "AGENT_ID": "1"}) == (
        IdentityMode.AGENT,
        "AGENT_ID",
    )


def test_auto_falls_back_to_human_without_recognized_markers():
    assert resolve_identity_mode(configured(), {"CI": "true", "TERM": "dumb"}) == (
        IdentityMode.HUMAN,
        None,
    )


def test_configured_agent_mode_does_not_require_markers():
    assert resolve_identity_mode(configured(default_mode=IdentityMode.AGENT), {}) == (
        IdentityMode.AGENT,
        None,
    )


def test_configured_human_mode_ignores_markers():
    assert resolve_identity_mode(
        configured(default_mode=IdentityMode.HUMAN), {"AGENT_ID": "1"}
    ) == (
        IdentityMode.HUMAN,
        None,
    )


def test_custom_markers_are_recognized_without_vendor_markers():
    config = configured(custom_agent_markers=("MY_CI_RUNNER", "CUSTOM_AGENT_ENV"))
    assert resolve_identity_mode(config, {"CUSTOM_AGENT_ENV": ""}) == (
        IdentityMode.AGENT,
        "CUSTOM_AGENT_ENV",
    )


def test_disabling_vendor_detection_ignores_vendor_markers():
    assert resolve_identity_mode(configured(vendor_detection=False), {"AGENT_ID": "1"}) == (
        IdentityMode.HUMAN,
        None,
    )


def test_custom_markers_still_work_when_vendor_detection_disabled():
    config = configured(vendor_detection=False, custom_agent_markers=("MY_RUNNER",))
    assert resolve_identity_mode(config, {"AGENT_ID": "1", "MY_RUNNER": "yes"}) == (
        IdentityMode.AGENT,
        "MY_RUNNER",
    )


def test_omitted_environment_reads_process_environment_but_empty_mapping_does_not(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE", "private-agent-value")
    assert resolve_identity_mode(configured()) == (IdentityMode.AGENT, "CLAUDE_CODE")
    assert resolve_identity_mode(configured(), {}) == (IdentityMode.HUMAN, None)


def test_unknown_mode_is_rejected_instead_of_silently_enabling_human():
    with pytest.raises(ValueError):
        resolve_identity_mode(configured(), {"UV_SHIM_GIT_MODE": "agnet"})
