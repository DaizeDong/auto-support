#!/usr/bin/env python3
"""auto-support — escalation to the founder (the one and only fallback action).

Architecture: when the bot is not allowed or not able to answer, the ONLY thing it may do is
escalate. This module makes "escalate" an observable, de-bounced action so relay never becomes
an alert storm (which collapses founder ack-rate). It shells out to a local notifier script
(config `AUTO_SUPPORT_NOTIFIER`, default `~/.local/notifier.py`) by default; a per-product
webhook can override it.

SRE-style alert governance (architecture 4.3):
  - dedup/group: identical (topic,user,intent) inside the cooldown window is suppressed
  - cooldown: same fingerprint not re-paged within dedup_window_sec (default 4h)
  - severity routing: 'critical' (suspected leak / credential hit / injection) always pages;
    'low' (ordinary low-confidence) is rate-limited
PRIVACY: detected secrets and PII are redacted from the entire notification.
Callers supply public citations only, never private source text.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import hashlib
from pathlib import Path
import re
from urllib.parse import urlsplit
from dataclasses import dataclass
from contextlib import contextmanager
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runtime_data import state_path as _state_path, DataBoundaryError  # noqa: E402
from sanitization import redact as _redact  # noqa: E402

DEFAULT_RELAY = os.path.expanduser(os.environ.get("AUTO_SUPPORT_NOTIFIER", "~/.local/notifier.py"))
CRITICAL = {"suspected_leak", "credential_hit", "injection", "pii_hit", "canary"}


def _fingerprint(topic: str, user_id: str, intent: str) -> str:
    return hashlib.sha256(("%s|%s|%s" % (topic, user_id, intent)).encode()).hexdigest()[:16]


def _load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as stream:
            state = json.load(stream)
    except FileNotFoundError:
        return {}
    if not isinstance(state, dict) or any(not isinstance(v, dict) or (type(v.get("last_sent")) not in (int, float) or not math.isfinite(v["last_sent"])) for v in state.values()):
        raise ValueError("Escalation state is invalid; repair it before sending")
    return state


def _save_state(path: str, state: dict) -> None:
    destination = Path(path)
    if Path(_state_path(path)) != destination:
        raise DataBoundaryError("State destination changed before saving")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    stream = tmp.open("x", encoding="utf-8")
    try:
        with stream:
            json.dump(state, stream)
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)


@dataclass
class _DispatchState:
    delivered: bool = False
    outcome_unknown: bool = False
    committed: bool = False
    cleanup_failed: bool = False


class StateLockCleanupError(OSError):
    """An owned state lock could not be removed after a definite pre-dispatch failure."""


@contextmanager
def _state_lock(path):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if Path(_state_path(path)) != destination:
        raise DataBoundaryError("State destination changed before locking")
    lock = destination.with_name(destination.name + ".lock")
    dispatch = _DispatchState()
    try:
        stream = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise RuntimeError("Escalation state is locked; check the previous dispatch before retrying") from exc
    try:
        # Only this call's successfully created lock enters cleanup, including write/close failures.
        with stream:
            stream.write("escalation dispatch in progress\n")
        yield dispatch
    finally:
        # A possible or confirmed delivery without committed state must not be retried.
        if (not dispatch.delivered and not dispatch.outcome_unknown) or dispatch.committed:
            try:
                lock.unlink()
            except OSError as exc:
                if not dispatch.delivered:
                    raise StateLockCleanupError(
                        "Escalation state lock cleanup failed; check the retained lock before retrying"
                    ) from exc
                dispatch.cleanup_failed = True


@dataclass
class EscalationResult:
    sent: bool | None
    suppressed: bool
    severity: str
    fingerprint: str
    reason: str = ""
    reconciliation_required: bool = False
    delivery_outcome: str = "not_started"


def escalate(question: str, *, trigger: str, user_id: str = "", channel: str = "",
             answer_ref: str = "", relay_cmd: str | None = None, webhook: str | None = None,
             dedup_window_sec: int = 14400, state_path: str | None = None,
             now: float | None = None, dry_run: bool = False) -> EscalationResult:
    now = now if now is not None else time.time()
    severity = "critical" if trigger in CRITICAL else "low"
    topic = _redact(question)[:80]
    fp = _fingerprint(topic, user_id + "|" + channel, intent=trigger)
    if dry_run:
        return EscalationResult(False, False, severity, fp, "dry_run")
    state_path = str(_state_path(state_path))

    with _state_lock(state_path) as dispatch:
        state = _load_state(state_path)
        last = state.get(fp, {}).get("last_sent")
        # critical always pages; low respects the cooldown window
        if severity != "critical" and last is not None and (now - last) < dedup_window_sec:
            return EscalationResult(False, True, severity, fp, "cooldown")

        body = (
            "auto-support escalation [%s]\n"
            "trigger: %s\n"
            "user: %s  channel: %s\n"
            "question: %s\n"
            "citations: %s\n"
            "action: needs founder review (bot did not answer)."
        ) % (severity.upper(), trigger, user_id or "?", channel or "?", topic, answer_ref or "-")

        body = _redact(body)

        sent = False
        if webhook:
            dispatch.outcome_unknown = True
            try:
                sent = _post_webhook(webhook, body)
            except Exception:
                # The adapter may have started I/O before an unexpected failure.
                sent = None
        else:
            # Explicit relay wins; otherwise select only an existing configured script.
            if relay_cmd:
                argv = [sys.executable, relay_cmd, body]
            else:
                rp = os.environ.get("SCHEDULE_RELAY_PY", "")
                rp = os.path.expanduser(rp) if rp else ""
                if rp and os.path.isfile(rp):
                    argv = [sys.executable, rp, "send", "--stream", "support", "--text", body]
                elif os.path.isfile(DEFAULT_RELAY):
                    argv = [sys.executable, DEFAULT_RELAY, body]
                else:
                    argv = None
            if argv:
                dispatch.outcome_unknown = True
                try:
                    response = subprocess.run(argv, capture_output=True, text=True, timeout=20)
                except (FileNotFoundError, PermissionError):
                    # The operating system refused to start the relay process.
                    sent = False
                except Exception:
                    sent = None
                else:
                    try:
                        receipt = json.loads(response.stdout) if response.returncode == 0 else {}
                        confirmed = (isinstance(receipt, dict) and receipt.get("sent") is True
                                     and receipt.get("dry_run") is False)
                    except (TypeError, ValueError):
                        confirmed = False
                    # Missing or negative receipts cannot prove the receiver saw nothing.
                    sent = True if confirmed else None
        if sent is not True and sent is not False:
            sent = None
        if sent is True:
            dispatch.delivered = True
        dispatch.outcome_unknown = sent is None
        result = EscalationResult(
            sent, False, severity, fp,
            "delivery_outcome_unknown" if sent is None else ("" if sent else "relay_unavailable"),
            reconciliation_required=sent is None,
            delivery_outcome="unknown" if sent is None else ("confirmed" if sent else "not_started"))
        if sent:
            state[fp] = {"last_sent": now, "severity": severity}
            try:
                _save_state(state_path, state)
            except Exception:
                # Delivery is confirmed; an exception cannot make it safe to resend.
                result.reason = "delivered_but_uncommitted"
                result.reconciliation_required = True
            else:
                dispatch.committed = True
    if dispatch.cleanup_failed:
        result.reason = "delivered_but_cleanup_failed"
        result.reconciliation_required = True
    return result

def _post_webhook(url: str, content: str) -> bool | None:
    """Return True for confirmed delivery, False before the request, or None when unknown."""
    import urllib.request
    # only allow the Discord webhook host (narrow egress; no arbitrary outbound)
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname in ("discord.com", "discordapp.com")
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password
                 and not parsed.fragment and not parsed.query
                 and re.fullmatch(r"/api/webhooks/[0-9]+/[A-Za-z0-9_.-]+", parsed.path))
    except ValueError:
        valid = False
    if not valid:
        return False
    if len(content) > 1900:
        # a founder reads this in Discord: say the body was cut instead of posting a partial
        content = content[:1900] + ("\n...[truncated, %d chars total]" % len(content))

    try:
        data = json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode()
        req = urllib.request.Request(url, data=data, headers={
            "Content-Type": "application/json",
            "User-Agent": "AgentCenter-AutoSupport/1.0 (+https://discord.com)",
        })
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect)
    except Exception as exc:
        print("[escalate] webhook request not started: %s" % type(exc).__name__, file=sys.stderr)
        return False
    try:
        with opener.open(req, timeout=20) as response:
            return True if 200 <= response.status < 300 else None
    except Exception as exc:
        # Once open begins, failure cannot establish that the receiver accepted nothing.
        print("[escalate] webhook delivery outcome unknown (timeout=20s): %s" % type(exc).__name__,
              file=sys.stderr)
        return None



def main():
    ap = argparse.ArgumentParser(description="escalate an uncertain/unsafe support turn to the founder")
    ap.add_argument("--question", required=True)
    ap.add_argument("--trigger", required=True)
    ap.add_argument("--user-id", default="")
    ap.add_argument("--channel", default="")
    ap.add_argument("--answer-ref", default="")
    ap.add_argument("--relay-cmd", default=None)
    ap.add_argument("--webhook", default=None)
    ap.add_argument("--dedup-window-sec", type=int, default=14400)
    ap.add_argument("--state-path", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        r = escalate(a.question, trigger=a.trigger, user_id=a.user_id, channel=a.channel,
                     answer_ref=a.answer_ref, relay_cmd=a.relay_cmd, webhook=a.webhook,
                     dedup_window_sec=a.dedup_window_sec, state_path=a.state_path, dry_run=a.dry_run)
    except (RuntimeError, OSError, ValueError) as exc:
        detail = str(exc) if isinstance(exc, (DataBoundaryError, StateLockCleanupError)) else type(exc).__name__
        print("Escalation failed: " + detail, file=sys.stderr)
        return 1
    print(json.dumps(r.__dict__, indent=2))
    if r.reconciliation_required:
        return 1
    return 0 if r.sent or r.suppressed or a.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
