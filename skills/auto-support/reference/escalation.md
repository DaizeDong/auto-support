# Escalation, the one and only fallback action

When the bot is not allowed or not able to answer, the ONLY thing it may do is escalate. This is
codified abstention: `scripts/escalate.py` makes "escalate" an observable, de-bounced action so
relay never becomes an alert storm (which would crater founder ack-rate).

## Triggers (multi-signal OR; business rules outrank confidence)
(a) denylist topic/path hit (even if source could answer) · (b) answer not groundable to the
allowlist · (c) secret/PII/credential detected · (d) injection/social-engineering classified ·
(e) multi-turn running risk over threshold · (f) structured canary tripped · (g) user explicitly
asks for a human. Any one -> escalate.

## SRE-style governance (implemented in escalate.py)
- **dedup/cooldown:** identical (topic,user,channel,trigger) fingerprint suppressed within
  `dedup_window_sec` (default 4h) after successful delivery. Failed delivery remains retryable.
  Critical severity bypasses cooldown. An exclusive state lock prevents overlapping dispatch;
  after a process crash, inspect the prior delivery before removing a stale lock.
- **severity routing:** `critical` = suspected_leak / credential_hit / injection / pii_hit /
  canary -> always page; `low` = ordinary low-confidence -> rate-limited.
- **privacy:** detected credentials and PII are redacted from the complete notification,
  including question, user, channel, trigger and citation fields. Supply public citations
  (path:line), never private source text. Pattern detection is not a guarantee that arbitrary
  private prose can be safely published.

## Transport
Default relay = a local notifier script (config `AUTO_SUPPORT_NOTIFIER`, default
`~/.local/notifier.py`). A per-product webhook may override; webhook host is restricted to
`discord.com/api/webhooks/` (narrow egress,
no arbitrary outbound), HTTPS only and no redirects. `--dry-run` returns `sent=false` with
`reason=dry_run`; it neither reads nor changes delivery state. A real transport failure exits
nonzero. A relay must exit 0 and emit a JSON object containing the exact booleans
`"sent": true` and `"dry_run": false` on stdout before cooldown is recorded. Missing fields,
invalid JSON, dry-run receipts and string booleans fail delivery. Adapt legacy notifiers
to this receipt contract; exit status alone cannot prove delivery.

State is resolved through `scripts/runtime_data.py` into a verified PRIVATE GitHub companion.
Missing or unknown visibility stops before sending. Do not put state or private observations
in the public tool repository. The draft pipeline requests escalation but never invokes this
transport automatically; sending requires authorization from the surrounding workflow.

## Reminder persistence

`reminder_bridge.py` records turns through the schedule-reminder CLI. Success requires an
absolute database selected with `--db` or `SCHEDULE_DB_PATH`, and a live PRIVATE repository
proof before each writing invocation. The database and its sidecars must stay in that repository;
hard links and unknown storage are rejected before the CLI runs. Success also requires an
`api_version` in 1.x, positive integer `schema_version`, exact `ok: true`, and an item with a
nonempty ID and recognized state. A transition must confirm the same ID and requested state.
Malformed receipts, incompatible versions and invocation failures exit nonzero; a zero process
exit alone does not confirm persistence. The CLI always emits JSON and has no `--json` flag.

Repeated message IDs reuse the same ticket. Existing done or cancelled tickets remain closed,
and a replay does not repeat a transition already reached. An abstention leaves work already
in progress unchanged. Reopening a closed ticket is a separate explicit reminder operation.

## Tuning (conservative start)
Start over-escalating (recovering from a bad answer costs more than an extra page). Track weekly:
mis-escalation rate, founder ack-rate, escalations/question. A trigger with >30% mis-escalation or
<50% ack gets re-thresholded or removed. High-frequency escalated questions become new allowlist
FAQ entries, which naturally lowers future escalation.
