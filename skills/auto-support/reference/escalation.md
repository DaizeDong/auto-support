# Escalation — the one and only fallback action

When the bot is not allowed or not able to answer, the ONLY thing it may do is escalate. This is
codified abstention: `scripts/escalate.py` makes "escalate" an observable, de-bounced action so
relay never becomes an alert storm (which would crater founder ack-rate).

## Triggers (multi-signal OR; business rules outrank confidence)
(a) denylist topic/path hit (even if source could answer) · (b) answer not groundable to the
allowlist · (c) secret/PII/credential detected · (d) injection/social-engineering classified ·
(e) multi-turn running risk over threshold · (f) structured canary tripped · (g) user explicitly
asks for a human. Any one -> escalate.

## SRE-style governance (implemented in escalate.py)
- **dedup/cooldown:** identical (topic,user,trigger) fingerprint suppressed within
  `dedup_window_sec` (default 4h). Critical severity bypasses cooldown.
- **severity routing:** `critical` = suspected_leak / credential_hit / injection / pii_hit /
  canary -> always page; `low` = ordinary low-confidence -> rate-limited.
- **privacy:** the question is PII-redacted before it leaves the machine; only citations
  (path:line) travel, never source text or secrets.

## Transport
Default relay = `the notifier` (machine Big-Brother bot). A per-product
webhook may override; webhook host is restricted to `discord.com/api/webhooks/` (narrow egress,
no arbitrary outbound). `--dry-run` reports as delivered with no side effect (for tests).

## Tuning (conservative start)
Start over-escalating (recovering from a bad answer costs more than an extra page). Track weekly:
mis-escalation rate, founder ack-rate, escalations/question. A trigger with >30% mis-escalation or
<50% ack gets re-thresholded or removed. High-frequency escalated questions become new allowlist
FAQ entries, which naturally lowers future escalation.
