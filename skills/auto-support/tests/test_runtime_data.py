"""Path-only runtime output admission inside a synthetic companion worktree."""
from pathlib import Path
import os

import pytest

import runtime_data as D
from conftest import companion_worktree
from test_review_acceptance_a import fixtures


@pytest.fixture
def private(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-companion"
    root.mkdir()
    companion_worktree(monkeypatch, root)
    tool = tmp_path / "synthetic-tool"
    tool.mkdir()
    monkeypatch.setattr(D, "REPO_ROOT", tool)
    monkeypatch.setattr(D, "_guard_base", lambda: root)
    return root


def test_output_resolves_inside_verified_private_companion_without_writing(private):
    path = D.state_path("incidents/state.json")
    assert path == private / "incidents/state.json"
    assert not path.parent.exists()


@pytest.mark.parametrize("value", ["../escape.json", ".git/state.json", "state.json.", "x:stream", ""])
def test_output_rejects_unsafe_relative_path(private, value):
    with pytest.raises(D.DataBoundaryError):
        D.state_path(value)


def test_absolute_outside_target_is_rejected(private):
    with pytest.raises(D.DataBoundaryError):
        D.state_path(private.parent / "outside.json")


def test_output_outside_any_git_worktree_is_rejected(tmp_path, monkeypatch):
    plain = tmp_path / "plain-directory"
    plain.mkdir()
    monkeypatch.setattr(D, "REPO_ROOT", tmp_path / "synthetic-tool")
    monkeypatch.setattr(D, "_guard_base", lambda: plain)
    with pytest.raises(D.DataBoundaryError, match="Git worktree"):
        D.state_path("state.json")
    assert not (plain / "state.json").exists()


def test_runtime_checks_start_no_process(private, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("runtime check started a process"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("runtime check started a process"))
    assert D.state_path("state.json") == private / "state.json"
    assert D.private_file_path(private / "support.db", sidecars=("-wal",)) == private / "support.db"


def test_tool_repository_never_qualifies_as_companion(private, monkeypatch):
    monkeypatch.setattr(D, "REPO_ROOT", private)
    with pytest.raises(D.DataBoundaryError):
        D.state_path("state.json")


def test_explicit_missing_config_does_not_select_default(tmp_path, monkeypatch):
    for name in ("AUTO_SUPPORT_DATA_DIR", "AUTO_SUPPORT_CONFIG", "AUTO_SUPPORT_CONFIG_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AUTO_SUPPORT_CONFIG", str(tmp_path / "missing"))
    with pytest.raises(D.DataBoundaryError, match="existing"):
        D._guard_base()


def test_nested_repository_cannot_capture_output(private):
    nested = private / "nested"
    (nested / ".git").mkdir(parents=True)
    with pytest.raises(D.DataBoundaryError, match="repository boundary"):
        D.state_path("nested/state.json")


def test_database_and_sidecars_are_verified_without_creation(private):
    target = private / "support.db"
    assert D.private_file_path(target, sidecars=("-wal", "-shm", "-journal")) == target
    assert [p.name for p in private.iterdir()] == [".git"]


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
def test_database_hardlink_cannot_share_runtime_bytes(private, suffix):
    outside = private.parent / "synthetic-other-file"
    outside.write_text("synthetic", encoding="utf-8")
    target = private / "support.db"
    os.link(outside, str(target) + suffix)
    with pytest.raises(D.DataBoundaryError, match="hard link"):
        D.private_file_path(target, sidecars=("-wal", "-shm", "-journal"))
    assert outside.read_text() == "synthetic"


@pytest.mark.parametrize("relative", [".git/support.db", "nested/../support.db", "support.db.", "NUL.db", "x:stream"])
def test_database_rejects_unsafe_components(private, relative):
    with pytest.raises(D.DataBoundaryError):
        D.private_file_path(private / relative)


@pytest.mark.parametrize("suffix", fixtures.escalation_endpoint_cases())
def test_escalation_rejects_aliased_write_endpoints(private, monkeypatch, suffix):
    import escalate as E

    target = private / "state.json"
    endpoint = target.with_name(target.name + suffix)
    outside = private.parent / "synthetic-state-peer"
    outside.write_text(fixtures.FILES["escalation_state.json.example"], encoding="utf-8")
    os.link(outside, endpoint)
    dispatched = []
    monkeypatch.setattr(E, "_post_webhook", lambda *args: dispatched.append(True))
    with pytest.raises(D.DataBoundaryError, match="hard link"):
        E.escalate("Synthetic question", trigger="low_confidence", webhook="synthetic",
                   state_path=str(target))
    assert not dispatched
