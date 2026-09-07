"""Annotated tags record the bot tagger without changing the tagged commit."""

from git_author_shim.cli import run_git

_CONFIG = """[[identities]]
id = "acme"
name = "Acme Bot"
email = "bot@acme.invalid"
match_patterns = ["github.com/acme/*"]
"""


def test_annotated_tag_records_bot_tagger(isolated_env, temp_repo, monkeypatch):
    isolated_env.write_config(_CONFIG)
    repo = temp_repo(remotes={"origin": "git@github.com:acme/app.git"})
    original = repo.git("cat-file", "commit", "HEAD").stdout
    monkeypatch.chdir(repo.path)
    monkeypatch.setenv("UV_SHIM_GIT_MODE", "agent")
    monkeypatch.setenv("UV_SHIM_GIT_REAL_PATH", repo.git_binary)
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Human Operator")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "human@example.invalid")

    assert run_git(["tag", "-a", "v1.0", "-m", "release"]) == 0

    assert (
        repo.git(
            "for-each-ref", "--format=%(taggername) <%(taggeremail:trim)>", "refs/tags/v1.0"
        ).stdout.strip()
        == "Acme Bot <bot@acme.invalid>"
    )
    assert repo.git("cat-file", "commit", "v1.0^{}").stdout == original
