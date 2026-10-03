"""Native selected-kit transport integration with generated local Git/profile state."""
import os
from pathlib import Path

import pytest

import runtime_data as D
from conftest import actual_private_proof
from test_review_acceptance_a import fixtures


@pytest.mark.parametrize("kind", ["https", "ssh-unproved-alias",
                                  "ssh-mapped-host", "ssh-proxy"])
@pytest.mark.parametrize("purpose", ["escalation", "database"])
def test_selected_public_api_proves_transport_before_live_visibility(tmp_path, monkeypatch, kind, purpose):
    actual_private_proof(monkeypatch, tmp_path)
    case = fixtures.public_transport_case(tmp_path, kind)
    for name in tuple(os.environ):
        if name.startswith(("GIT_", "AUTO_SUPPORT_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(case["profile"]))
    monkeypatch.setenv("USERPROFILE", str(case["profile"]))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(case["empty_config"]))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setattr(D, "_guard_base", lambda: case["companion"])
    queries = []

    def query(argv, **kwargs):
        assert argv == ["gh", "api", "--hostname", "github.com",
                        "repos/example-owner/example-config", "--jq", ".private"]
        queries.append(argv)
        return "true"

    monkeypatch.setattr(D, "_run", query)
    target = case["companion"] / ("state.json" if purpose == "escalation" else "support.db")
    invoke = (lambda: D.state_path(target.name)) if purpose == "escalation" else (
        lambda: D.private_file_path(target, sidecars=("-wal", "-shm", "-journal")))
    if case["allowed"]:
        assert invoke() == target
        assert queries
    else:
        with pytest.raises(D.DataBoundaryError):
            invoke()
        assert not queries
    assert not target.exists()


def test_missing_public_proof_dependency_blocks_before_visibility(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "REPO_ROOT", tmp_path / "uninitialized-tool")
    monkeypatch.setattr(D, "_run", lambda *_args, **_kwargs: pytest.fail("query before proof"))
    with pytest.raises(D.DataBoundaryError, match="guards kit"):
        D.private_file_path(tmp_path / "support.db")
