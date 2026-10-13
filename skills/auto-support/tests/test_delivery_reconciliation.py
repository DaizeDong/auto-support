"""Offline HTTPS admission and delivered-but-uncommitted regression controls."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

import escalate as E

spec = importlib.util.spec_from_file_location(
    "reconciliation_fixtures", Path(__file__).resolve().parents[3] / "tools/make_fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


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
