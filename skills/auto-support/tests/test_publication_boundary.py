"""Exercise actual Git URL resolution with synthetic visibility transport only."""
import os
import subprocess

import pytest

import runtime_data as D
from test_review_acceptance_a import fixtures


@pytest.fixture
def companion(tmp_path, monkeypatch, request):
    kind = request.param
    root = fixtures.companion_repository_case(tmp_path / "companion", kind)
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="ascii")
    for name in list(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_OPTIONAL_LOCKS", "0")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setattr(D, "REPO_ROOT", tmp_path / "tool")
    monkeypatch.setattr(D, "_guard_base", lambda: root)
    real_run = subprocess.run

    def transport(argv, **kwargs):
        if argv[0] == "gh":
            assert argv[:4] == ["gh", "api", "--hostname", "github.com"]
            assert argv[5:] == ["--jq", ".private"]
            values = {"repos/example-owner/example-config": "true",
                      "repos/example-owner/public-fixture": "false"}
            value = "null" if kind == "unknown-visibility" else values[argv[4]]
            return subprocess.CompletedProcess(argv, 0, value + "\n", "")
        assert argv[0] == "git"
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", transport)
    try:
        yield root
    finally:
        (root / ".git").rename(root / "retired-git-fixture")


@pytest.mark.parametrize("companion", ["private", "private-secondary"], indirect=True)
def test_all_private_destinations_allow_runtime_paths_without_writing(companion):
    assert D.state_path("state.json") == companion / "state.json"
    assert D.private_file_path(companion / "turns.db") == companion / "turns.db"
    assert not (companion / "state.json").exists()
    assert not (companion / "turns.db").exists()


@pytest.mark.parametrize("companion", [
    "public-pushurl", "multiple-pushurls", "push-rewrite", "fetch-rewrite",
    "push-default", "branch-push", "branch-remote", "unnamed-push-default",
    "no-remotes", "unknown-visibility",
], indirect=True)
def test_unproved_publication_destination_refuses_before_runtime_write(companion):
    with pytest.raises(D.DataBoundaryError):
        D.state_path("state.json")
    with pytest.raises(D.DataBoundaryError):
        D.private_file_path(companion / "turns.db", sidecars=("-wal", "-shm", "-journal"))
    assert not (companion / "state.json").exists()
    assert not (companion / "turns.db").exists()
