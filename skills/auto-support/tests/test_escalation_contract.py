"""Delivery/state regressions. All notifications are intercepted before I/O."""
import pytest

import escalate as E


@pytest.fixture
def state(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-state.json"
    monkeypatch.setattr(E, "_state_path", lambda value: path, raising=False)
    return path


def test_dry_run_is_not_delivery_and_does_not_write_state(state, monkeypatch):
    monkeypatch.setattr(E, "_post_webhook", lambda *args: pytest.fail("unexpected send"))
    result = E.escalate("synthetic question", trigger="low_confidence", state_path=str(state), dry_run=True)
    assert not result.sent
    assert result.reason == "dry_run"
    assert not state.exists()


def test_failed_delivery_does_not_suppress_retry(state, monkeypatch):
    outcomes = iter([False, True])
    monkeypatch.setattr(E, "_post_webhook", lambda *args: next(outcomes))
    first = E.escalate("synthetic question", trigger="low_confidence", state_path=str(state), webhook="synthetic", now=20000)
    assert not first.sent
    assert not state.exists()
    retry = E.escalate("synthetic question", trigger="low_confidence", state_path=str(state), webhook="synthetic", now=20001)
    assert retry.sent and not retry.suppressed


def test_corrupt_state_fails_before_send(state, monkeypatch):
    state.write_text("broken", encoding="utf-8")
    monkeypatch.setattr(E, "_post_webhook", lambda *args: pytest.fail("unexpected send"))
    with pytest.raises((ValueError, RuntimeError)):
        E.escalate("synthetic", trigger="low_confidence", state_path=str(state), webhook="synthetic")


def test_busy_state_lock_blocks_duplicate_dispatch(state, monkeypatch):
    state.with_name(state.name + ".lock").write_text("synthetic lock", encoding="utf-8")
    monkeypatch.setattr(E, "_post_webhook", lambda *args: pytest.fail("unexpected send"))
    with pytest.raises(RuntimeError, match="locked"):
        E.escalate("synthetic", trigger="low_confidence", state_path=str(state), webhook="synthetic")


def test_first_delivery_with_small_clock_is_not_suppressed(state, monkeypatch):
    monkeypatch.setattr(E, "_post_webhook", lambda *args: True)
    result = E.escalate("synthetic", trigger="low_confidence", state_path=str(state), webhook="synthetic", now=1)
    assert result.sent and not result.suppressed


@pytest.mark.parametrize("url", [
    "https://example.com/?next=discord.com/api/webhooks/123/fake",
    "https://discord.com.example.com/api/webhooks/123/fake",
    "http://discord.com/api/webhooks/123/fake",
    "https://user1@example.com/discord.com/api/webhooks/123/fake",
])
def test_webhook_host_validation_never_requests_invalid_target(url, monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: pytest.fail("unexpected network"))
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: pytest.fail("unexpected network"))
    assert not E._post_webhook(url, "synthetic")
