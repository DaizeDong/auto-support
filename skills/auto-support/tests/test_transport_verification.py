"""Consumer routing checks with generated transport responses and no network access."""
import importlib.util
import os
from pathlib import Path

import pytest

import runtime_data as D

spec = importlib.util.spec_from_file_location(
    "transport_fixtures", Path(__file__).resolve().parents[3] / "tools/make_fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


@pytest.mark.parametrize("kind", fixtures.companion_transport_kinds())
@pytest.mark.parametrize("purpose", ["escalation", "database"])
def test_transport_must_be_proved_before_runtime_path_is_admitted(tmp_path, monkeypatch, kind, purpose):
    case = fixtures.companion_transport_case(tmp_path, kind)
    for name in tuple(os.environ):
        if name.startswith(("GIT_", "AUTO_SUPPORT_")):
            monkeypatch.delenv(name)
    for name, value in case["environment"].items():
        monkeypatch.setenv(name, value)
    companion = case["companion"]
    monkeypatch.setattr(D, "REPO_ROOT", case["tool"])
    monkeypatch.setattr(D, "_guard_base", lambda: companion)
    commands = []

    def command(argv, **kwargs):
        commands.append(tuple(argv))
        if argv[0] == "git":
            if "rev-parse" in argv:
                return str(companion)
            if argv[3:] == ["remote"]:
                return "origin"
            if "--get-regexp" in argv:
                return ""
            if argv[3:] == ["config", "--null", "--list"]:
                return case["configuration"]
            if argv[3:5] == ["remote", "get-url"]:
                return case["remote"]
        if argv[0] == "gh":
            return "true"
        pytest.fail("Unproved transport command was requested: " + argv[0])

    monkeypatch.setattr(D, "_run", command)
    target = companion / ("state.json" if purpose == "escalation" else "support.db")

    def resolve():
        if purpose == "escalation":
            return D.state_path(target.name)
        return D.private_file_path(target, sidecars=("-wal", "-shm", "-journal"))

    if case["allowed"]:
        assert resolve() == target
        assert any(argv[0] == "gh" for argv in commands)
    else:
        with pytest.raises(D.DataBoundaryError):
            resolve()
        assert not any(argv[0] == "gh" for argv in commands)
    assert list(companion.iterdir()) == []
    assert not any(argv[0] == "ssh" for argv in commands)
