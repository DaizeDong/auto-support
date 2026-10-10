"""The live PRIVATE check must not depend on which gh account is ACTIVE.

A plain `gh api repos/OWNER/NAME --jq .private` asks only with the account `gh auth switch` last
selected. When another session switched it to an account that cannot see the companion, every
proof failed closed. The query now goes through the pinned Guards kit, which asks every stored gh
account. These tests run the REAL kit against a synthetic gh (the kit's own fixture generator)
whose active account cannot see the repository; nothing here touches the real gh.
"""
import importlib.util
import os
import subprocess

import pytest

import runtime_data as D

REPOSITORY = "example-owner/example-config"
ARGV = ["gh", "api", "--hostname", "github.com", "repos/" + REPOSITORY, "--jq", ".private"]


def _kit_fixtures():
    path = D.REPO_ROOT / "guards/tools/make_fixtures.py"
    spec = importlib.util.spec_from_file_location("_auto_support_make_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _switched_gh(tmp_path, monkeypatch, visibility):
    fixtures = _kit_fixtures()
    stub = fixtures.make_gh_cli_stub(tmp_path, accounts=["example-owner", "other-account"],
                                     active="other-account", sees={"example-owner": [REPOSITORY]},
                                     visibility={REPOSITORY: visibility})
    monkeypatch.setenv("PATH", str(stub["bin"]))
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_HOST", "GH_ENTERPRISE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return fixtures, stub


def test_switched_active_account_still_proves_private(tmp_path, monkeypatch):
    fixtures, stub = _switched_gh(tmp_path, monkeypatch, "PRIVATE")
    assert D._run(list(ARGV)) == "true"
    calls = fixtures.gh_stub_calls(stub)
    assert not [call for call in calls if call["argv"][:2] == ["auth", "switch"]]
    assert [call["credential"] for call in calls if call["argv"][:2] == ["repo", "view"]] == ["example-owner"]


@pytest.mark.parametrize("visibility", ["PUBLIC", "INTERNAL"])
def test_public_repository_is_never_reported_private(tmp_path, monkeypatch, visibility):
    _switched_gh(tmp_path, monkeypatch, visibility)
    assert D._run(list(ARGV)) == "false"


def test_plain_active_account_query_is_the_incident(tmp_path, monkeypatch):
    """Negative control: the stub's active account cannot see the repository, as on 2026-10-09."""
    _fixtures, stub = _switched_gh(tmp_path, monkeypatch, "PRIVATE")
    result = subprocess.run([str(stub["launcher"]), "repo", "view", REPOSITORY, "--json", "nameWithOwner,visibility"],
                            capture_output=True, text=True, env=dict(os.environ, GH_HOST="github.com"),
                            **({"creationflags": 0x08000000} if os.name == "nt" else {}))
    assert result.returncode != 0


def test_no_credential_can_see_it_refuses(tmp_path, monkeypatch):
    fixtures = _kit_fixtures()
    stub = fixtures.make_gh_cli_stub(tmp_path, accounts=["example-owner"], active="example-owner",
                                     sees={}, visibility={REPOSITORY: "PRIVATE"})
    monkeypatch.setenv("PATH", str(stub["bin"]))
    with pytest.raises(D.DataBoundaryError, match="no gh credential"):
        D._run(list(ARGV))


def test_a_kit_without_the_api_refuses(monkeypatch):
    class Kit:
        GitError = RuntimeError
    monkeypatch.setattr(D, "_boundary_module", lambda: Kit)
    with pytest.raises(D.DataBoundaryError, match="account-independent"):
        D._run(list(ARGV))
