from pathlib import Path

import pytest

from git_author_shim.config import ConfigError, default_config_path, load_config
from git_author_shim.data_models import IdentityMode


def write_toml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "git.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_a_single_identity_with_all_settings_and_credentials(tmp_path: Path) -> None:
    path = write_toml(
        tmp_path,
        """
[settings]
default_mode = "agent"
vendor_detection = false
custom_agent_markers = ["CUSTOM_AGENT_ENV", "MY_CI_RUNNER"]

[[identities]]
id = "acme-github"
name = "Acme Automation Bot"
email = "bot@acme.test"
match_patterns = ["github.com/acme/*"]

[identities.ssh]
key_file = "~/.ssh/acme_bot_ed25519"
strict_host_checking = false

[identities.https]
token_env_var = "ACME_BOT_TOKEN"
username = "oauth2"
""",
    )

    config = load_config(path)

    assert config.settings.default_mode is IdentityMode.AGENT
    assert config.settings.vendor_detection is False
    assert config.settings.custom_agent_markers == (
        "CUSTOM_AGENT_ENV",
        "MY_CI_RUNNER",
    )
    assert len(config.identities) == 1
    identity = config.identities[0]
    assert identity.id == "acme-github"
    assert identity.name == "Acme Automation Bot"
    assert identity.email == "bot@acme.test"
    assert identity.match_patterns == ("github.com/acme/*",)
    assert identity.ssh is not None
    assert identity.ssh.key_file == Path("~/.ssh/acme_bot_ed25519")
    assert identity.ssh.strict_host_checking is False
    assert identity.https is not None
    assert identity.https.token_env_var == "ACME_BOT_TOKEN"
    assert identity.https.username == "oauth2"


def test_loads_multiple_identity_tables_and_all_https_source_variants(tmp_path: Path) -> None:
    path = write_toml(
        tmp_path,
        """
[[identities]]
id = "from-file"
name = "File Bot"
email = "file@example.test"
match_patterns = ["github.com/file/*"]
[identities.https]
token_file = "secrets/github-token"

[[identities]]
id = "from-command"
name = "Command Bot"
email = "command@example.test"
match_patterns = ["gitlab.com/command/*"]
[identities.https]
token_command = "secret-tool lookup service gitlab"
""",
    )

    config = load_config(path)

    assert [identity.id for identity in config.identities] == ["from-file", "from-command"]
    assert config.identities[0].https is not None
    assert config.identities[0].https.token_file == Path("secrets/github-token")
    assert config.identities[1].https is not None
    assert config.identities[1].https.token_command == "secret-tool lookup service gitlab"


def test_settings_default_to_auto_with_vendor_detection_enabled(tmp_path: Path) -> None:
    path = write_toml(
        tmp_path,
        """
[[identities]]
id = "bot"
name = "Bot"
email = "bot@example.test"
match_patterns = ["example.test/team/*"]
""",
    )

    settings = load_config(path).settings

    assert settings.default_mode is IdentityMode.AUTO
    assert settings.vendor_detection is True
    assert settings.custom_agent_markers == ()


def test_missing_default_config_returns_an_empty_safe_configuration(tmp_path: Path) -> None:
    config = load_config(tmp_path / "does-not-exist.toml")

    assert config.settings.default_mode is IdentityMode.AUTO
    assert config.identities == ()


def test_default_config_path_is_home_git_shim_config_toml(isolated_env) -> None:
    assert default_config_path() == isolated_env.home / ".git-shim" / "config.toml"


def test_default_config_path_honors_git_shim_config(isolated_env, tmp_path) -> None:
    override = tmp_path / "custom.toml"
    isolated_env.setenv("GIT_SHIM_CONFIG", str(override))
    assert default_config_path() == override


def test_default_config_path_uses_git_toml_when_config_toml_is_absent(isolated_env) -> None:
    legacy = isolated_env.home / ".git-shim" / "git.toml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("[settings]\n", encoding="utf-8")
    assert default_config_path() == legacy


def test_default_config_path_prefers_config_toml_over_git_toml(isolated_env) -> None:
    directory = isolated_env.home / ".git-shim"
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "config.toml"
    config.write_text("[settings]\n", encoding="utf-8")
    (directory / "git.toml").write_text("[settings]\n", encoding="utf-8")
    assert default_config_path() == config


@pytest.mark.parametrize("missing_field", ["id", "name", "email", "match_patterns"])
def test_rejects_an_identity_missing_a_required_field(tmp_path: Path, missing_field: str) -> None:
    fields = {
        "id": 'id = "bot"',
        "name": 'name = "Bot"',
        "email": 'email = "bot@example.test"',
        "match_patterns": 'match_patterns = ["example.test/team/*"]',
    }
    body = "\n".join(value for key, value in fields.items() if key != missing_field)
    path = write_toml(tmp_path, f"[[identities]]\n{body}\n")

    with pytest.raises(ConfigError, match=rf"identities\[0\]\.{missing_field}.*required"):
        load_config(path)


def test_wraps_invalid_toml_with_the_config_path(tmp_path: Path) -> None:
    path = write_toml(tmp_path, '[settings\ndefault_mode = "auto"')

    with pytest.raises(ConfigError, match=r"invalid TOML.*git\.toml") as error:
        load_config(path)

    assert error.value.__cause__ is not None


@pytest.mark.parametrize(
    ("toml_text", "message"),
    [
        ('[settings]\ndefault_mode = "robot"', "settings.default_mode"),
        ('[settings]\nvendor_detection = "yes"', "settings.vendor_detection"),
        ('[settings]\ncustom_agent_markers = ["GOOD", 7]', "custom_agent_markers"),
        (
            '[[identities]]\nid = "bot"\nname = "Bot"\nemail = "bot@example.test"\n'
            "match_patterns = []",
            "match_patterns",
        ),
        (
            '[[identities]]\nid = "bot"\nname = "Bot"\nemail = "bot@example.test"\n'
            'match_patterns = ["example.test/*"]\n[identities.https]\n'
            'token_env_var = "TOKEN"\ntoken_file = "token.txt"',
            "exactly one token source",
        ),
        (
            '[[identities]]\nid = "same"\nname = "One"\nemail = "one@example.test"\n'
            'match_patterns = ["example.test/one/*"]\n[[identities]]\nid = "same"\n'
            'name = "Two"\nemail = "two@example.test"\n'
            'match_patterns = ["example.test/two/*"]',
            "duplicate identity id",
        ),
    ],
)
def test_rejects_schema_validation_errors(tmp_path: Path, toml_text: str, message: str) -> None:
    path = write_toml(tmp_path, toml_text)

    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_rejects_unknown_fields_instead_of_silently_ignoring_typos(tmp_path: Path) -> None:
    path = write_toml(tmp_path, "[settings]\nvendor_autodetection = true")

    with pytest.raises(ConfigError, match="unknown field.*vendor_autodetection"):
        load_config(path)
