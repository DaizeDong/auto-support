
"""Synthetic receiver-acceptance controls for uncertain notification outcomes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import urllib.request

import pytest
import escalate as E

spec = importlib.util.spec_from_file_location(
    "unknown_delivery_fixtures", Path(__file__).resolve().parents[3] / "tools/make_fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def install_transport(case, tmp_path, monkeypatch):
    path = tmp_path / "synthetic-state.json"
    monkeypatch.setattr(E, "_state_path", lambda value: path)
    accepted, attempts = [], []
    def execute():
        number = len(attempts)
        attempts.append(case["transport"])
        failure = case["failure"] if number == 0 else "healthy"
        if failure == "not_found":
            raise FileNotFoundError("Synthetic process did not start")
        if failure == "permission":
            raise PermissionError("Synthetic process did not start")
        if failure == "prepare_error":
            raise OSError("Synthetic webhook request was not started")
        accepted.append(case["question"])
        if failure == "timeout":
            if case["transport"] == "relay":
                raise subprocess.TimeoutExpired(["synthetic"], 20)
            raise TimeoutError("Synthetic receiver accepted before timeout")
        if failure == "connection_lost":
            raise ConnectionResetError("Synthetic receiver accepted before disconnect")
        if failure == "unexpected_error":
            raise RuntimeError("Synthetic response processing failed")
        if case["transport"] == "relay":
            outputs = {
                "invalid_json": "invalid",
                "empty_receipt": "{}",
                "missing_field": json.dumps({"sent": True}),
                "negative_receipt": json.dumps({"sent": False, "dry_run": False}),
                "string_boolean": json.dumps({"sent": "true", "dry_run": False}),
            }
            return SimpleNamespace(returncode=1 if failure == "nonzero_exit" else 0,
                stdout=outputs.get(failure, json.dumps({"sent": True, "dry_run": False})))
        class Response:
            status = 500 if failure == "non_success" else 204
            def __enter__(self): return self
            def __exit__(self, *args):
                if failure == "response_exit_error":
                    raise ConnectionResetError("Synthetic response close failed")
                return False
        return Response()
    if case["transport"] == "relay":
        monkeypatch.setattr(E.subprocess, "run", lambda *args, **kwargs: execute())
        kwargs = {"relay_cmd": case["relay"]}
    else:
        class Opener:
            def open(self, *args, **kwargs): return execute()
        def build(*args):
            if case["failure"] == "prepare_error" and not attempts:
                return execute()
            return Opener()
        monkeypatch.setattr(urllib.request, "build_opener", build)
        kwargs = {"webhook": case["webhook"]}
    kwargs.update(trigger=case["trigger"], now=case["now"], state_path=str(path))
    return path, accepted, attempts, kwargs


@pytest.mark.parametrize("case", fixtures.unknown_delivery_cases(), ids=lambda case: case["id"])
def test_receiver_acceptance_without_confirmation_blocks_duplicate(case, tmp_path, monkeypatch):
    path, accepted, attempts, kwargs = install_transport(case, tmp_path, monkeypatch)
    if case["unknown"]:
        monkeypatch.setattr(E, "_save_state", lambda *args: pytest.fail("unknown delivery started cooldown"))
    first = E.escalate(case["question"], **kwargs)
    lock = path.with_name(path.name + ".lock")
    if case["unknown"]:
        assert first.sent is None
        assert first.delivery_outcome == "unknown"
        assert first.reconciliation_required is True
        assert first.reason == "delivery_outcome_unknown"
        assert lock.is_file() and lock.read_text()
        assert not path.exists()
        with pytest.raises(RuntimeError, match="locked"):
            E.escalate(case["question"], **kwargs)
        # Critical alerts cannot bypass an unresolved in-flight dispatch.
        kwargs["trigger"] = "suspected_leak"
        with pytest.raises(RuntimeError, match="locked"):
            E.escalate(case["question"], **kwargs)
        assert accepted == [case["question"]] and len(attempts) == 1
    elif case["failure"] == "healthy":
        assert first.sent is True and first.delivery_outcome == "confirmed"
        assert not first.reconciliation_required and not lock.exists()
        second = E.escalate(case["question"], **kwargs)
        assert second.suppressed and len(accepted) == 1
    else:
        assert first.sent is False and first.delivery_outcome == "not_started"
        assert not first.reconciliation_required and not lock.exists() and not path.exists()
        second = E.escalate(case["question"], **kwargs)
        assert second.sent is True and len(accepted) == 1 and len(attempts) == 2


@pytest.mark.parametrize("transport", ["relay", "webhook"])
def test_cli_reports_unknown_without_claiming_nondelivery(transport, tmp_path, monkeypatch, capsys):
    case = next(case for case in fixtures.unknown_delivery_cases()
                if case["transport"] == transport and case["failure"] == "timeout")
    path, accepted, attempts, kwargs = install_transport(case, tmp_path, monkeypatch)
    command = ["escalate.py", "--question", case["question"], "--trigger", case["trigger"]]
    command += ["--relay-cmd", case["relay"]] if transport == "relay" else ["--webhook", case["webhook"]]
    monkeypatch.setattr(sys, "argv", command)
    assert E.main() == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["sent"] is None and receipt["delivery_outcome"] == "unknown"
    assert receipt["reconciliation_required"] is True
    assert len(accepted) == 1 and path.with_name(path.name + ".lock").is_file()


def test_interruption_after_request_begins_keeps_dispatch_protection(tmp_path, monkeypatch):
    case = fixtures.unknown_delivery_cases()[0]
    path, accepted, attempts, kwargs = install_transport(case, tmp_path, monkeypatch)
    def interrupted(*args, **options):
        accepted.append(case["question"])
        raise KeyboardInterrupt()
    monkeypatch.setattr(E.subprocess, "run", interrupted)
    with pytest.raises(KeyboardInterrupt):
        E.escalate(case["question"], **kwargs)
    assert path.with_name(path.name + ".lock").is_file()
    with pytest.raises(RuntimeError, match="locked"):
        E.escalate(case["question"], **kwargs)
    assert accepted == [case["question"]]
