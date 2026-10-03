"""Bind path admission to physical Git administration using generated inputs."""
import ast
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

import runtime_data as D
from conftest import actual_private_proof, private_proof

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("administration_fixtures", ROOT / "tools/make_fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


@pytest.mark.parametrize("kind", fixtures.companion_administration_kinds())
@pytest.mark.parametrize("purpose", ["database", "escalation"])
def test_physical_repository_proof_rejects_administrative_redirection(tmp_path, monkeypatch, kind, purpose):
    actual_private_proof(monkeypatch, tmp_path)
    case = fixtures.companion_administration_case(tmp_path, kind)
    for name in tuple(os.environ):
        if name.startswith(("GIT_", "AUTO_SUPPORT_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(case["empty_config"]))
    for name, value in case["environment"].items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(D, "REPO_ROOT", case["tool"])
    monkeypatch.setattr(D, "_guard_base", lambda: case["physical"])
    actual_run = subprocess.run
    commands = []

    def transport(argv, **kwargs):
        commands.append(tuple(argv))
        if argv[0] == "gh":
            assert argv[:4] == ["gh", "api", "--hostname", "github.com"]
            assert argv[5:] == ["--jq", ".private"]
            visibility = {"repos/example-owner/example-config": "true",
                          "repos/example-owner/public-fixture": "false"}
            return subprocess.CompletedProcess(argv, 0, visibility[argv[4]] + "\n", "")
        assert Path(argv[0]).stem.casefold() == "git"
        return actual_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", transport)
    target = case["physical"] / ("support.db" if purpose == "database" else "state.json")
    def resolve():
        if purpose == "database":
            return D.private_file_path(target, sidecars=("-wal", "-shm", "-journal"))
        return D.state_path(target.name)
    try:
        if case["allowed"]:
            assert resolve() == target
            assert any(argv[0] == "gh" for argv in commands)
        else:
            with pytest.raises(D.DataBoundaryError):
                resolve()
        if case["environment"]:
            assert commands == [], "Ambient administrative overrides must fail before proof commands"
        assert not target.exists()
        assert not any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
    finally:
        for admin in sorted(tmp_path.rglob(".git"), key=lambda path: len(path.parts), reverse=True):
            admin.rename(admin.with_name("retired-git-fixture"))


@pytest.mark.parametrize("relative,fixture_name", [
    ("test_review_round2.py", "private_receipt_fixture"),
    ("test_reminder_bridge.py", "db"),
    ("test_review_acceptance_a.py", "test_reminder_rejects_unproven_database_before_invocation"),
])
def test_existing_visibility_callback_supports_public_proof_adapter(tmp_path, monkeypatch, relative, fixture_name):
    case = fixtures.companion_administration_case(tmp_path, "private")
    source = Path(__file__).with_name(relative).read_text(encoding="utf-8")
    outer = next(node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == fixture_name)
    command = next(node for node in outer.body if isinstance(node, ast.FunctionDef) and node.name == "command")
    module = ast.fix_missing_locations(ast.Module(body=[command], type_ignores=[]))
    namespace = {"pytest": pytest, "D": D, "root": case["physical"],
                 "tmp_path": case["physical"], "visibility": "true"}
    exec(compile(module, relative, "exec"), namespace)
    monkeypatch.setattr(D, "REPO_ROOT", case["tool"])
    private_proof(monkeypatch, case["physical"])
    monkeypatch.setattr(D, "_run", namespace["command"])
    target = case["physical"] / "support.db"
    assert D.private_file_path(target) == target
    assert not target.exists()
    with pytest.raises(pytest.fail.Exception):
        namespace["command"](["git", "-C", str(case["physical"]), "unexpected-command"])
