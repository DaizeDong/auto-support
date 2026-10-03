"""Offline HTTPS admission and delivered-but-uncommitted regression controls."""
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

import escalate as E
import reminder_bridge as B
import runtime_data as D
from conftest import private_proof

spec = importlib.util.spec_from_file_location(
    "reconciliation_fixtures", Path(__file__).resolve().parents[3] / "tools/make_fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


@pytest.mark.parametrize("name,value,allowed", fixtures.live_visibility_environment_cases())
@pytest.mark.parametrize("purpose", ["escalation", "database"])
def test_live_visibility_overrides_fail_before_creation_or_dispatch(tmp_path, monkeypatch, name, value, allowed, purpose):
    for key in tuple(os.environ):
        if key.casefold() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy",
                              "curl_ca_bundle", "ssl_cert_file", "ssl_cert_dir"}:
            monkeypatch.delenv(key)
    if name:
        monkeypatch.setenv(name, value)
    private_proof(monkeypatch, tmp_path)
    monkeypatch.setattr(D, "_guard_base", lambda: tmp_path)
    commands, dispatches = [], []

    def command(argv, **kwargs):
        assert argv[0] == "gh"
        commands.append(tuple(argv))
        return "true"

    monkeypatch.setattr(D, "_run", command)
    monkeypatch.setattr(E, "_post_webhook", lambda *args: dispatches.append("webhook") or True)

    def reminder(*args, **kwargs):
        dispatches.append("reminder")
        return type("Receipt", (), {"returncode": 0, "stdout": json.dumps({
            "ok": True, "api_version": "1.0.0", "schema_version": 1,
            "item": {"id": "synthetic-item", "state": "pending"},
        })})()

    monkeypatch.setattr(B.subprocess, "run", reminder)
    target = tmp_path / "new" / ("state.json" if purpose == "escalation" else "support.db")

    def invoke():
        if purpose == "escalation":
            return E.escalate("Synthetic question", trigger="low_confidence",
                              webhook="synthetic", state_path=str(target), now=20000)
        return B._call("add", [], db=str(target))

    if allowed:
        invoke()
        assert dispatches == ["webhook" if purpose == "escalation" else "reminder"]
        assert commands
    else:
        with pytest.raises((D.DataBoundaryError, B.ReminderError), match="HTTPS"):
            invoke()
        assert not dispatches and not commands and not target.parent.exists()


def delivery_case(tmp_path, monkeypatch, kind):
    case = fixtures.escalation_reconciliation_case(tmp_path, kind)
    path = case["path"]
    monkeypatch.setattr(E, "_state_path", lambda value: path)
    deliveries = []
    outcomes = iter(case["outcomes"])

    def deliver(*args):
        result = next(outcomes)
        deliveries.append(result)
        return result

    monkeypatch.setattr(E, "_post_webhook", deliver)
    arguments = {key: case[key] for key in ("trigger", "webhook", "now")}
    arguments["state_path"] = str(path)
    return case, deliveries, arguments


@pytest.mark.parametrize("kind", ["write", "state-cleanup", "lock-cleanup"])
def test_confirmed_delivery_failure_retains_lock_and_blocks_resend(tmp_path, monkeypatch, kind):
    case, deliveries, arguments = delivery_case(tmp_path, monkeypatch, kind)
    path = case["path"]
    lock = path.with_name(path.name + ".lock")
    if kind == "write":
        def fail_save(*args):
            raise OSError("Synthetic persistence failure")
        monkeypatch.setattr(E, "_save_state", fail_save)
    else:
        unlink = Path.unlink
        def fail_cleanup(target, *args, **kwargs):
            if ((kind == "lock-cleanup" and target == lock)
                    or (kind == "state-cleanup" and target.parent == path.parent and target != lock)):
                raise OSError("Synthetic cleanup failure")
            return unlink(target, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", fail_cleanup)

    result = E.escalate(case["question"], **arguments)
    assert result.sent and not result.suppressed
    assert result.reconciliation_required
    assert result.reason == ("delivered_but_cleanup_failed" if kind == "lock-cleanup"
                             else "delivered_but_uncommitted")
    assert lock.is_file()
    with pytest.raises(RuntimeError, match="locked"):
        E.escalate(case["question"], **arguments)
    assert deliveries == [True]


@pytest.mark.parametrize("kind", ["healthy", "failed-send", "critical"])
def test_delivery_controls_preserve_cooldown_retry_and_critical_semantics(tmp_path, monkeypatch, kind):
    case, deliveries, arguments = delivery_case(tmp_path, monkeypatch, kind)
    first = E.escalate(case["question"], **arguments)
    second = E.escalate(case["question"], **arguments)
    assert not getattr(first, "reconciliation_required", False)
    assert not getattr(second, "reconciliation_required", False)
    if kind == "healthy":
        assert first.sent and second.suppressed and not second.sent
        assert deliveries == [True]
    else:
        assert second.sent and not second.suppressed
        assert deliveries == ([False, True] if kind == "failed-send" else [True, True])
    assert not case["path"].with_name(case["path"].name + ".lock").exists()


def test_cli_reports_confirmed_delivery_and_requires_reconciliation(tmp_path, monkeypatch, capsys):
    case, deliveries, arguments = delivery_case(tmp_path, monkeypatch, "write")
    def fail_save(*args):
        raise OSError("Synthetic persistence failure")
    monkeypatch.setattr(E, "_save_state", fail_save)
    monkeypatch.setattr(sys, "argv", ["escalate.py", "--question", case["question"],
                                    "--trigger", case["trigger"], "--webhook", case["webhook"]])
    assert E.main() == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["sent"] is True
    assert receipt["reconciliation_required"] is True
    assert receipt["reason"] == "delivered_but_uncommitted"
    assert deliveries == [True]
