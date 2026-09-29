"""Private output proofs using synthetic Git/visibility responses at the I/O seam."""
from pathlib import Path
import os

import pytest

import runtime_data as D


@pytest.fixture
def private(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-companion"
    root.mkdir()
    tool = tmp_path / "synthetic-tool"
    tool.mkdir()
    monkeypatch.setattr(D, "REPO_ROOT", tool)
    monkeypatch.setattr(D, "_guard_base", lambda: root)
    def command(argv, **kwargs):
        if argv[0] == "git":
            if "rev-parse" in argv:
                return str(root)
            if argv[3:] == ["remote"]:
                return "origin"
            if "--get-regexp" in argv:
                return ""
            if argv[3:5] == ["remote", "get-url"]:
                return "https://github.com/example-owner/example-config.git"
            pytest.fail("unexpected Git command")
        if argv[0] == "gh":
            return "true"
        pytest.fail("unexpected command")
    monkeypatch.setattr(D, "_run", command)
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


@pytest.mark.parametrize("visibility", ["false", "null", "", "PRIVATE"])
def test_unknown_or_public_visibility_rejects_before_write(private, monkeypatch, visibility):
    original = D._run
    monkeypatch.setattr(D, "_run", lambda args, **kwargs: visibility if args[0] == "gh" else original(args, **kwargs))
    with pytest.raises(D.DataBoundaryError, match="visibility"):
        D.state_path("state.json")
    assert not (private / "state.json").exists()


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


def test_nested_repository_cannot_capture_output(private, monkeypatch):
    nested = private / "nested"
    nested.mkdir()
    original = D._run
    def command(args, **kwargs):
        if args[0] == "git" and "rev-parse" in args and args[2] == str(nested):
            return str(nested)
        return original(args, **kwargs)
    monkeypatch.setattr(D, "_run", command)
    with pytest.raises(D.DataBoundaryError, match="repository boundary"):
        D.state_path("nested/state.json")


def test_database_and_sidecars_are_verified_without_creation(private):
    target = private / "support.db"
    assert D.private_file_path(target, sidecars=("-wal", "-shm", "-journal")) == target
    assert list(private.iterdir()) == []


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
