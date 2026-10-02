#!/usr/bin/env python3
"""auto-support -> schedule-reminder bridge (reuse the frozen base; never reinvent state).

We persist every support turn (pending / doing / done-FAQ / blocked-escalation / cancelled)
through the schedule-reminder contract (api_version 1.x). We ONLY call `reminder.py <verb>`
over subprocess and parse its always-JSON stdout. We NEVER touch the .db, write SQL, or import
base internals (contract.md hard rule).

auto-support fields ride in `ext` under the `x_auto_support_*` namespace (base MUST-PRESERVE).
Idempotency key = `auto-support:discord:<message_id>` so a redelivered Discord event is a
no-op upsert, not a duplicate ticket.

PRIVACY: detected credentials and PII are redacted from text and metadata before
persistence. Callers supply only public citations in `x_auto_support_answer_ref`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sanitization import redact, sanitize_fields  # noqa: E402
import runtime_data as D  # noqa: E402

# Resolve the base CLI. Override with AUTO_SUPPORT_REMINDER_PY for tests / non-default installs.
DEFAULT_REMINDER = os.path.expanduser("~/.local/reminder.py")
REMINDER_PY = os.environ.get("AUTO_SUPPORT_REMINDER_PY", DEFAULT_REMINDER)


class ReminderError(RuntimeError):
    pass


_STATES = {"pending", "doing", "done", "blocked", "cancelled"}
_TARGETS = {"answered": "done", "doing": "doing", "escalate": "blocked",
            "blocked-leak": "blocked", "abstain": "pending", "cancelled": "cancelled"}


def _validate_receipt(receipt: object) -> dict:
    """Require the versioned success envelope and the item fields this bridge uses."""
    if not isinstance(receipt, dict) or receipt.get("ok") is not True:
        raise ReminderError("reminder did not confirm persistence")
    version = receipt.get("api_version")
    schema = receipt.get("schema_version")
    if (not isinstance(version, str) or not re.fullmatch(r"1\.\d+\.\d+", version)
            or type(schema) is not int or schema < 1):
        raise ReminderError("reminder returned an unsupported receipt version")
    item = receipt.get("item")
    if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
            or not item["id"].strip() or not isinstance(item.get("state"), str)
            or item["state"] not in _STATES):
        raise ReminderError("reminder returned an invalid item receipt")
    return receipt


def _call(verb: str, args: list[str], db: str | None = None) -> dict:
    try:
        selected = db if db is not None else os.environ.get("SCHEDULE_DB_PATH")
        if selected is None:
            raise D.DataBoundaryError("Set --db or SCHEDULE_DB_PATH to an absolute database in a PRIVATE versioned companion")
        target = D.private_file_path(selected, sidecars=("-wal", "-shm", "-journal"))
    except (D.DataBoundaryError, OSError, ValueError) as exc:
        raise ReminderError(str(exc)) from exc
    cmd = [sys.executable, REMINDER_PY, "--db", str(target)]
    cmd += ["--actor", "auto-support", verb] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=60)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as exc:
        raise ReminderError("reminder invocation failed; persistence is unconfirmed") from exc
    if p.returncode == 0:
        try:
            receipt = json.loads(p.stdout)
        except (ValueError, TypeError) as e:
            raise ReminderError("reminder returned invalid JSON") from e
        return _validate_receipt(receipt)
    # structured error on stderr
    try:
        err = json.loads(p.stderr)
    except (ValueError, TypeError):
        err = None
    if not isinstance(err, dict):
        raise ReminderError("reminder invocation failed without a structured error")
    raise ReminderError(redact("%s: %s" % (err.get("error_code"), err.get("message"))))


def _ext(message_id: str, channel: str, user_id: str, intent: str, decision: str,
         trigger: str = "", retrieval_conf: float | None = None,
         faithfulness: float | None = None, answer_ref: str = "",
         question: str = "") -> str:
    ext = {
        "x_auto_support_question": question,
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
    return json.dumps(sanitize_fields({k: v for k, v in ext.items() if v not in ("", None)}))


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

    An existing terminal item is returned without reopening it. Replaying a state
    already reached performs no further transitions. Receipt mismatches fail loudly.
    """
    if not isinstance(message_id, str) or not message_id or redact(message_id) != message_id:
        raise ReminderError("message_id must be a nonempty identifier without sensitive content")
    if decision not in _TARGETS:
        raise ReminderError("unsupported support decision")
    title = "[support] " + redact(question)[:80]
    ext = _ext(message_id, channel, user_id, intent, decision, trigger,
               retrieval_conf, faithfulness, answer_ref, question)
    idem = "auto-support:discord:%s" % message_id
    item = _call("add", [
        "--title", title, "--kind", "task", "--state", "pending",
        "--source", "auto-support", "--idempotency-key", idem, "--ext", ext,
    ], db)["item"]
    iid, state = item["id"], item["state"]
    if state in ("done", "cancelled") or state == _TARGETS[decision]:
        return item

    def transition(verb: str, args: list[str], target: str) -> dict:
        updated = _call(verb, ["--id", iid] + args, db)["item"]
        if updated["id"] != iid or updated["state"] != target:
            raise ReminderError("reminder receipt does not confirm the requested transition")
        return updated

    if decision in ("escalate", "blocked-leak"):
        reason = "leak-blocked" if decision == "blocked-leak" else (trigger or "low-confidence")
        return transition("block", ["--reason", redact(reason)], "blocked")
    if decision == "answered":
        if state != "doing":
            transition("transition", ["--to", "doing", "--expect", state], "doing")
        return transition("done", [], "done")
    if decision == "doing":
        return transition("transition", ["--to", "doing", "--expect", state], "doing")
    if decision == "cancelled":
        return transition("transition", ["--to", "cancelled", "--expect", state,
                                         "--reason", "off-topic/chitchat"], "cancelled")
    return item  # abstain does not reset a ticket that is already being handled


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
