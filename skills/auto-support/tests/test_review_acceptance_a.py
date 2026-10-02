"""Public-content integrity and private persistence regression contracts."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import answer_pipeline as AP
import reminder_bridge as RB
import runtime_data as D
from test_first_run_contract import run_script, SCRIPTS

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("content_fixture_generator", ROOT / "tools/make_fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


@pytest.mark.parametrize("kind", ["spaces", "long"])
def test_complete_public_instruction_remains_answerable(tmp_path, kind):
    relative, content = fixtures.content_integrity_case(tmp_path, kind)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    assert result.decision == "answered"
    assert content.decode().strip() in result.response_text
    assert result.citations == [relative + ":1"]


@pytest.mark.parametrize("kind", ["invalid-utf8", "over-budget"])
def test_unusable_instruction_never_becomes_trusted_partial_answer(tmp_path, kind):
    fixtures.content_integrity_case(tmp_path, kind)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    assert result.decision != "answered"
    assert result.faithfulness != 1.0
    assert "\ufffd" not in result.response_text


@pytest.mark.parametrize("visibility", ["false", "null", "", "unknown-origin"])
def test_reminder_rejects_unproven_database_before_invocation(tmp_path, monkeypatch, visibility):
    root = tmp_path / "companion"
    root.mkdir()
    calls = []

    def command(argv, **kwargs):
        if argv[0] == "git":
            if "rev-parse" in argv:
                return str(root)
            if visibility == "unknown-origin":
                raise D.DataBoundaryError("origin missing")
            if argv[3:] == ["remote"]:
                return "origin"
            if "--get-regexp" in argv:
                return ""
            if argv[3:] == ["config", "--null", "--list"]:
                return ""
            if argv[3:5] == ["remote", "get-url"]:
                return "https://github.com/example-owner/example-config.git"
            pytest.fail("unexpected private-boundary command")
        return visibility

    def invoke(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "ok": True, "schema_version": 1, "api_version": "1.0.0",
            "item": {"id": "synthetic-turn", "state": "pending"}}), stderr="")

    monkeypatch.setattr(D, "_run", command)
    monkeypatch.setattr(RB.subprocess, "run", invoke)
    with pytest.raises(RB.ReminderError):
        RB.record_turn("synthetic-message", channel="synthetic", user_id="synthetic", intent="unclear",
                       decision="abstain", question="synthetic question", db=str(root / "support.db"))
    assert calls == []
    assert not (root / "support.db").exists()


@pytest.mark.parametrize("selected", [None, "relative.db"])
def test_reminder_requires_explicit_absolute_private_database(monkeypatch, selected):
    monkeypatch.delenv("SCHEDULE_DB_PATH", raising=False)
    calls = []
    monkeypatch.setattr(RB.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(RB.ReminderError):
        RB._call("add", [], selected)
    assert not calls


def test_doctor_accepts_documented_explicit_policy_root(tmp_path):
    companion = tmp_path / "synthetic-companion"
    assert run_script(SCRIPTS / "init_config.py", "--out", companion).returncode == 0
    docs = tmp_path / "public-docs"
    fixtures.content_integrity_case(docs, "spaces")
    product_path = companion / "products/example/product.json"
    product = json.loads(product_path.read_text())
    product["product_root"] = str(docs)
    product_path.write_text(json.dumps(product), encoding="utf-8")
    policy_path = product_path.with_name("policy.json")
    policy = json.loads(policy_path.read_text())
    policy["product_root"] = str(docs)
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    checked = run_script(SCRIPTS / "verify_config.py", "--config-dir", companion)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "apply.py" not in checked.stdout
