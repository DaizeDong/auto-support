#!/usr/bin/env python3
"""auto-support — escalation to the founder (the one and only fallback action).

Architecture: when the bot is not allowed or not able to answer, the ONLY thing it may do is
escalate. This module makes "escalate" an observable, de-bounced action so relay never becomes
an alert storm (which collapses founder ack-rate). It reuses the machine's Discord relay
(`the notifier`) by default; a per-product webhook can override it.

SRE-style alert governance (architecture 4.3):
  - dedup/group: identical (topic,user,intent) inside the cooldown window is suppressed
  - cooldown: same fingerprint not re-paged within dedup_window_sec (default 4h)
  - severity routing: 'critical' (suspected leak / credential hit / injection) always pages;
    'low' (ordinary low-confidence) is rate-limited
PRIVACY: the question is PII-redacted before it leaves the machine; citations only, no source.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import hashlib
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrails as G  # noqa: E402

DEFAULT_RELAY = os.path.expanduser("the notifier")
DEFAULT_STATE = os.path.join(
    os.environ.get("AUTO_SUPPORT_STATE_DIR", os.path.expanduser("~/.auto-support")),
    "escalation_state.json",
)
CRITICAL = {"suspected_leak", "credential_hit", "injection", "pii_hit", "canary"}


def _redact(text: str) -> str:
    out = text or ""
    for (s0, s1), rule in sorted(((f.span, f.rule) for f in G.scan_pii(out).findings), reverse=True):
        out = out[:s0] + ("[REDACTED_%s]" % rule.upper()) + out[s1:]
    return out


def _fingerprint(topic: str, user_id: str, intent: str) -> str:
    return hashlib.sha256(("%s|%s|%s" % (topic, user_id, intent)).encode()).hexdigest()[:16]


def _load_state(path: str) -> dict:
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}


def _save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    json.dump(state, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, path)


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
    state_path = state_path or DEFAULT_STATE
    severity = "critical" if trigger in CRITICAL else "low"
    topic = _redact(question)[:80]
    fp = _fingerprint(topic, user_id, intent=trigger)

    state = _load_state(state_path)
    last = state.get(fp, {}).get("last_sent", 0)
    # critical always pages; low respects the cooldown window
    if severity != "critical" and (now - last) < dedup_window_sec:
        return EscalationResult(False, True, severity, fp, "cooldown")

    body = (
        "auto-support escalation [%s]\n"
        "trigger: %s\n"
        "user: %s  channel: %s\n"
        "question: %s\n"
        "citations: %s\n"
        "action: needs founder review (bot did not answer)."
    ) % (severity.upper(), trigger, user_id or "?", channel or "?", topic, answer_ref or "-")

    sent = False
    if not dry_run:
        if webhook:
            sent = _post_webhook(webhook, body)
        else:
            # Pluggable Agent Center egress: prefer schedule-reminder's unified relay (#support
            # stream) when the base is installed; else fall back to the Big Brother relay (send.py).
            # An explicit --relay-cmd still wins (legacy/override).
            if relay_cmd:
                argv = [sys.executable, relay_cmd, body]
            else:
                rp = os.environ.get("SCHEDULE_RELAY_PY") or os.path.expanduser(
                    "the stream relay")
                if os.path.isfile(rp):
                    argv = [sys.executable, rp, "send", "--stream", "support", "--text", body]
                elif os.path.isfile(DEFAULT_RELAY):
                    argv = [sys.executable, DEFAULT_RELAY, body]
                else:
                    argv = None
            if argv:
                try:
                    r = subprocess.run(argv, capture_output=True, text=True, timeout=20)
                    sent = r.returncode == 0
                except Exception:
                    sent = False
    else:
        sent = True  # dry-run reports as if delivered, no side effect

    state[fp] = {"last_sent": now, "severity": severity, "topic": topic}
    _save_state(state_path, state)
    return EscalationResult(sent, False, severity, fp, "" if sent else "relay_unavailable")


def _post_webhook(url: str, content: str) -> bool:
    import urllib.request
    # only allow the Discord webhook host (narrow egress; no arbitrary outbound)
    if "discord.com/api/webhooks/" not in url and "discordapp.com/api/webhooks/" not in url:
        return False
    data = json.dumps({"content": content[:1900], "allowed_mentions": {"parse": []}}).encode()
    # Discord/Cloudflare 403s the default urllib User-Agent — a real UA is mandatory.
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "AgentCenter-AutoSupport/1.0 (+https://discord.com)",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except Exception:
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
    r = escalate(a.question, trigger=a.trigger, user_id=a.user_id, channel=a.channel,
                 answer_ref=a.answer_ref, relay_cmd=a.relay_cmd, webhook=a.webhook,
                 dedup_window_sec=a.dedup_window_sec, state_path=a.state_path, dry_run=a.dry_run)
    print(json.dumps(r.__dict__, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
