#!/usr/bin/env python3
"""auto-support -> schedule-reminder bridge (reuse the frozen base; never reinvent state).

We persist every support turn (pending / doing / done-FAQ / blocked-escalation / cancelled)
through the schedule-reminder contract (api_version 1.0.0). We ONLY call `reminder.py <verb>
--json` over subprocess and parse stdout JSON. We NEVER touch the .db, write SQL, or import
base internals (contract.md hard rule).

auto-support fields ride in `ext` under the `x_auto_support_*` namespace (base MUST-PRESERVE).
Idempotency key = `auto-support:discord:<message_id>` so a redelivered Discord event is a
no-op upsert, not a duplicate ticket.

PRIVACY: the question is PII-redacted before it is stored (scan_pii -> redact), and
`x_auto_support_answer_ref` carries only citations (path:line), never secret/source text.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrails as G  # noqa: E402

# Resolve the base CLI. Override with AUTO_SUPPORT_REMINDER_PY for tests / non-default installs.
DEFAULT_REMINDER = os.path.expanduser(
    "the reminder base"
)
REMINDER_PY = os.environ.get("AUTO_SUPPORT_REMINDER_PY", DEFAULT_REMINDER)


class ReminderError(RuntimeError):
    pass


def _redact_pii(text: str) -> str:
    """Replace any PII span with a typed tag so nothing personal is persisted."""
    out = text or ""
    res = G.scan_pii(out)
    # rebuild from spans (right-to-left so offsets stay valid)
    spans = sorted(((f.span, f.rule) for f in res.findings), reverse=True)
    for (s0, s1), rule in spans:
        out = out[:s0] + ("[REDACTED_%s]" % rule.upper()) + out[s1:]
    return out


def _call(verb: str, args: list[str], db: str | None = None) -> dict:
    cmd = [sys.executable, REMINDER_PY]
    if db:
        cmd += ["--db", db]
    cmd += ["--actor", "auto-support", verb] + args
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode == 0:
        try:
            return json.loads(p.stdout.strip().splitlines()[-1])
        except Exception as e:
            raise ReminderError("bad stdout JSON: %s / %s" % (e, p.stdout[:200]))
    # structured error on stderr
    try:
        err = json.loads((p.stderr or "{}").strip().splitlines()[-1])
    except Exception:
        err = {"error_code": "ERR_UNKNOWN", "message": p.stderr[:200]}
    raise ReminderError("%s: %s" % (err.get("error_code"), err.get("message")))


def _ext(message_id: str, channel: str, user_id: str, intent: str, decision: str,
         trigger: str = "", retrieval_conf: float | None = None,
         faithfulness: float | None = None, answer_ref: str = "",
         question: str = "") -> str:
    ext = {
        "x_auto_support_question": _redact_pii(question),
        "x_auto_support_discord_msg_id": message_id,
        "x_auto_support_channel": channel,
        "x_auto_support_user_id": user_id,
        "x_auto_support_intent": intent,
        "x_auto_support_decision": decision,
        "x_auto_support_trigger": trigger,
        "x_auto_support_answer_ref": answer_ref,  # citations only, never source text
    }
    if retrieval_conf is not None:
        ext["x_auto_support_retrieval_conf"] = round(retrieval_conf, 3)
    if faithfulness is not None:
        ext["x_auto_support_faithfulness"] = round(faithfulness, 3)
    return json.dumps({k: v for k, v in ext.items() if v not in ("", None)})


def record_turn(message_id: str, *, channel: str, user_id: str, intent: str, decision: str,
                question: str, trigger: str = "", retrieval_conf: float | None = None,
                faithfulness: float | None = None, answer_ref: str = "",
                db: str | None = None) -> dict:
    """Upsert a ticket for one support turn. Returns the base `item`.

    decision -> base state mapping (architecture 6.2):
      answered     -> task/done  (FAQ sediment)         [we transition after upsert]
      doing        -> task/doing
      escalate     -> task/blocked  (reason=trigger)
      blocked-leak -> task/blocked  (reason=leak)
      abstain      -> task/pending  (stays queued for human)
      cancelled    -> cancelled
    """
    title = "[support] " + _redact_pii(question)[:80]
    ext = _ext(message_id, channel, user_id, intent, decision, trigger,
               retrieval_conf, faithfulness, answer_ref, question)
    idem = "auto-support:discord:%s" % message_id
    item = _call("add", [
        "--title", title, "--kind", "task", "--state", "pending",
        "--source", "auto-support", "--idempotency-key", idem, "--ext", ext,
    ], db).get("item", {})
    iid = item.get("id")
    if not iid:
        return item

    if decision in ("escalate", "blocked-leak"):
        reason = "leak-blocked" if decision == "blocked-leak" else (trigger or "low-confidence")
        return _call("block", ["--id", iid, "--reason", reason], db).get("item", item)
    if decision == "answered":
        _call("transition", ["--id", iid, "--to", "doing"], db)
        return _call("done", ["--id", iid], db).get("item", item)
    if decision == "doing":
        return _call("transition", ["--id", iid, "--to", "doing"], db).get("item", item)
    if decision == "cancelled":
        return _call("transition", ["--id", iid, "--to", "cancelled",
                                    "--reason", "off-topic/chitchat"], db).get("item", item)
    return item  # abstain -> leave pending


def main():
    ap = argparse.ArgumentParser(description="record an auto-support turn into schedule-reminder")
    ap.add_argument("--message-id", required=True)
    ap.add_argument("--channel", default="")
    ap.add_argument("--user-id", default="")
    ap.add_argument("--intent", default="product_usage_question")
    ap.add_argument("--decision", required=True,
                    choices=["answered", "doing", "abstain", "escalate", "blocked-leak", "cancelled"])
    ap.add_argument("--question", default="")
    ap.add_argument("--trigger", default="")
    ap.add_argument("--answer-ref", default="")
    ap.add_argument("--db", default=os.environ.get("SCHEDULE_DB_PATH"))
    a = ap.parse_args()
    item = record_turn(a.message_id, channel=a.channel, user_id=a.user_id, intent=a.intent,
                       decision=a.decision, question=a.question, trigger=a.trigger,
                       answer_ref=a.answer_ref, db=a.db)
    print(json.dumps({"ok": True, "id": item.get("id"), "state": item.get("state")}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ReminderError as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        sys.exit(1)
