"""Synthetic lock initialization and retry controls; no transport is executed."""
import builtins
import importlib.util
from pathlib import Path
import sys

import pytest
import escalate as E

spec = importlib.util.spec_from_file_location(
    "lock_initialization_fixtures", Path(__file__).resolve().parents[3] / "tools/make_fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def install_fault(case, tmp_path, monkeypatch):
    path = tmp_path / case["state_name"]
    lock = path.with_name(path.name + ".lock")
    monkeypatch.setattr(E, "_state_path", lambda value: path)
    deliveries, streams = [], []
    monkeypatch.setattr(E, "_post_webhook", lambda *args: deliveries.append(case["question"]) or True)
    initialization_error = getattr(builtins, case["exception"])(case["initialization_error"])
    original_open = Path.open

    class FaultyStream:
        def __init__(self, stream):
            self.stream = stream
            streams.append(stream)

        def __enter__(self):
            return self

        def write(self, content):
            if case["failure"] == "close":
                return self.stream.write(content)
            if case["failure"] == "partial-write":
                self.stream.write(content[:8])
            raise initialization_error

        def __exit__(self, *args):
            self.stream.close()
            if case["failure"] == "close":
                raise initialization_error
            return False

    def open_file(target, *args, **kwargs):
        stream = original_open(target, *args, **kwargs)
        if target == lock and args and args[0] == "x":
            return FaultyStream(stream)
        return stream

    monkeypatch.setattr(Path, "open", open_file)
    arguments = {key: case[key] for key in ("trigger", "webhook", "now")}
    arguments["state_path"] = str(path)
    return path, lock, deliveries, streams, initialization_error, arguments, original_open


@pytest.mark.parametrize("case", fixtures.lock_initialization_cases(), ids=lambda case: case["id"])
def test_lock_initialization_failure_releases_owned_lock_and_allows_retry(case, tmp_path, monkeypatch):
    path, lock, deliveries, streams, error, arguments, original_open = install_fault(
        case, tmp_path, monkeypatch)
    with pytest.raises(type(error)) as failure:
        E.escalate(case["question"], **arguments)
    assert failure.value is error
    assert deliveries == [] and not path.exists()
    assert len(streams) == 1 and streams[0].closed
    assert not lock.exists()

    monkeypatch.setattr(Path, "open", original_open)
    retry = E.escalate(case["question"], **arguments)
    assert retry.sent is True and retry.delivery_outcome == "confirmed"
    assert not retry.reconciliation_required and not lock.exists()
    assert path.is_file() and deliveries == [case["question"]]
    assert E.escalate(case["question"], **arguments).suppressed
    assert deliveries == [case["question"]]


@pytest.mark.parametrize("case", fixtures.lock_initialization_cases(), ids=lambda case: case["id"])
def test_initialization_cleanup_failure_is_explicit_and_keeps_retry_blocked(case, tmp_path, monkeypatch):
    path, lock, deliveries, streams, error, arguments, original_open = install_fault(
        case, tmp_path, monkeypatch)
    original_unlink = Path.unlink
    cleanup_error = PermissionError(case["cleanup_error"])
    removals = []

    def refuse_removal(target, *args, **kwargs):
        if target == lock:
            removals.append(target)
            raise cleanup_error
        return original_unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_removal)
    with pytest.raises(BaseException) as failure:
        E.escalate(case["question"], **arguments)
    assert isinstance(failure.value, OSError)
    assert "state lock cleanup failed" in str(failure.value)
    assert failure.value.__cause__ is cleanup_error
    assert cleanup_error.__context__ is error
    assert removals == [lock]
    assert streams[0].closed and lock.is_file()
    assert not path.exists() and deliveries == []

    monkeypatch.setattr(Path, "open", original_open)
    with pytest.raises(RuntimeError, match="locked"):
        E.escalate(case["question"], **arguments)
    assert removals == [lock] and deliveries == []


@pytest.mark.parametrize("content", fixtures.existing_lock_contents())
def test_existing_lock_is_never_removed_or_overwritten(content, tmp_path, monkeypatch):
    case = fixtures.lock_initialization_cases()[0]
    path, lock, deliveries, streams, error, arguments, original_open = install_fault(
        case, tmp_path, monkeypatch)
    lock.write_bytes(content)
    monkeypatch.setattr(Path, "unlink", lambda *args, **kwargs: pytest.fail("removed an existing lock"))
    with pytest.raises(RuntimeError, match="locked"):
        E.escalate(case["question"], **arguments)
    assert lock.read_bytes() == content and not path.exists()
    assert deliveries == [] and streams == []


def test_lock_open_refusal_does_not_attempt_cleanup(tmp_path, monkeypatch):
    case = fixtures.lock_initialization_cases()[0]
    path, lock, deliveries, streams, error, arguments, original_open = install_fault(
        case, tmp_path, monkeypatch)
    refusal = PermissionError(case["initialization_error"])

    def refuse_open(target, *args, **kwargs):
        if target == lock:
            raise refusal
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(Path, "open", refuse_open)
    monkeypatch.setattr(Path, "unlink", lambda *args, **kwargs: pytest.fail("removed an unowned lock"))
    with pytest.raises(PermissionError) as failure:
        E.escalate(case["question"], **arguments)
    assert failure.value is refusal
    assert not lock.exists() and not path.exists() and deliveries == [] and streams == []


@pytest.mark.parametrize("case", [case for case in fixtures.lock_initialization_cases()
                                  if case["id"] in {"write-oserror", "close-oserror"}],
                         ids=lambda case: case["id"])
def test_cli_identifies_lock_cleanup_failure_before_dispatch(case, tmp_path, monkeypatch, capsys):
    path, lock, deliveries, streams, error, arguments, original_open = install_fault(
        case, tmp_path, monkeypatch)
    original_unlink = Path.unlink

    def refuse_removal(target, *args, **kwargs):
        if target == lock:
            raise PermissionError(case["cleanup_error"])
        return original_unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuse_removal)
    monkeypatch.setattr(sys, "argv", ["escalate.py", "--question", case["question"],
                                    "--trigger", case["trigger"], "--webhook", case["webhook"]])
    assert E.main() == 1
    output = capsys.readouterr()
    assert not output.out
    assert "state lock cleanup failed" in output.err and "before retrying" in output.err
    assert lock.is_file() and not path.exists() and deliveries == []
