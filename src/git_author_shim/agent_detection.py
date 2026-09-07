"""Resolve human/agent mode with explicit overrides ahead of marker detection."""

import os

from git_author_shim.data_models import IdentityMode, ShimConfig

_VENDOR_MARKERS = (
    "AGENT_ID",
    "CLAUDE_CODE",
    "CLAUDE_AGENT",
    "CODEX_SANDBOX",
    "CURSOR_AGENT",
    "OPENAI_AGENT",
)


def resolve_identity_mode(config: ShimConfig, env=None) -> tuple[IdentityMode, str | None]:
    """Return the resolved mode and, for auto-detection, the marker's name.

    Marker presence is sufficient, even when its value is empty. Marker values
    are never returned: they can contain private agent identifiers. Disabling
    vendor detection does not disable explicitly configured custom markers.
    """
    if env is None:
        env = os.environ
    settings = config.settings
    mode = IdentityMode(env.get("UV_SHIM_GIT_MODE", settings.default_mode))
    if mode is not IdentityMode.AUTO:
        return mode, None
    if settings.vendor_detection:
        for marker in _VENDOR_MARKERS:
            if marker in env:
                return IdentityMode.AGENT, marker
    for marker in settings.custom_agent_markers:
        if marker in env:
            return IdentityMode.AGENT, marker
    return IdentityMode.HUMAN, None
