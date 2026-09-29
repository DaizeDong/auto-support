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
import tempfile
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path), delete=False) as stream:
        tmp = stream.name
        json.dump(state, stream)
    try:
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


@contextmanager
def _state_lock(path):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if Path(_state_path(path)) != destination:
        raise DataBoundaryError("State destination changed before locking")
    lock = destination.with_name(destination.name + ".lock")
    try:
        with lock.open("x", encoding="utf-8") as stream:
            stream.write("escalation dispatch in progress\n")
    except FileExistsError as exc:
        raise RuntimeError("Escalation state is locked; check the previous dispatch before retrying") from exc
    try:
        yield
    finally:
        lock.unlink()


@dataclass
class EscalationResult:
    sent: bool
    suppressed: bool
    severity: str
    fingerprint: str
    reason: str = ""


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

    with _state_lock(state_path):
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
        if not dry_run:
            if webhook:
                sent = _post_webhook(webhook, body)
            else:
                # Pluggable egress: prefer an external stream relay (e.g. a scheduler/notification
                # hub's unified relay) when SCHEDULE_RELAY_PY points at one; else fall back to the
                # notifier (DEFAULT_RELAY). An explicit --relay-cmd still wins (override).
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
                    try:
                        r = subprocess.run(argv, capture_output=True, text=True, timeout=20)
                        receipt = json.loads(r.stdout) if r.returncode == 0 else {}
                        sent = (isinstance(receipt, dict) and receipt.get("sent") is True
                                and receipt.get("dry_run") is False)
                    except (OSError, subprocess.TimeoutExpired, ValueError):
                        sent = False
        if sent:
            state[fp] = {"last_sent": now, "severity": severity}
            _save_state(state_path, state)
        return EscalationResult(sent, False, severity, fp, "" if sent else "relay_unavailable")

def _post_webhook(url: str, content: str) -> bool:
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
    data = json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode()
    # Discord/Cloudflare 403s the default urllib User-Agent, a real UA is mandatory.
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "AgentCenter-AutoSupport/1.0 (+https://discord.com)",
    })
    try:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with urllib.request.build_opener(NoRedirect).open(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        # escalation is the only fallback action: never drop it without a word
        print("[escalate] webhook post failed (timeout=20s): %s" % type(e).__name__,
              file=sys.stderr)
        return False


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
        detail = str(exc) if isinstance(exc, DataBoundaryError) else type(exc).__name__
        print("Escalation failed: " + detail, file=sys.stderr)
        return 1
    print(json.dumps(r.__dict__, indent=2))
    return 0 if r.sent or r.suppressed or a.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
