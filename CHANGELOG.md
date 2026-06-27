# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [0.1.1] - 2026-06-27
### Changed
- **Discord egress unified through Agent Center relay**: pushes now prefer schedule-reminder's
  `relay.py send --stream support` (per-stream identity in the Agent Center server) when the base
  is installed, and **fall back to the Big Brother relay (send.py) when it is not** — fully
  pluggable, no behaviour change when the base is absent. Existing env/arg overrides still win.

## [0.1.0] - 2026-06-25
### Added
- Initial release — leak-safe product Discord support answering (skill-as-plugin).
- Four fail-closed gates (`scripts/answer_pipeline.py`): entry (injection+intent) ->
  retrieval (allowlist-only, secret-scrubbed) -> grounding (retrieval-conf × faithfulness) ->
  egress (structured schema + DLP + canary + citation integrity).
- Deterministic guardrail engine (`scripts/guardrails.py`, stdlib): path knowledge boundary
  (allowlist-first / default-deny / denylist-wins), secret detection (regex + Shannon entropy,
  hash-only reporting), PII detection (Luhn-checked), injection/social-engineering detection
  (NFKC + zero-width + leetspeak + base64/hex decode + typoglycemia anagram + fuzzy phrases),
  spotlighting.
- Fail-closed `PreToolUse` hook (`scripts/pretooluse_hook.py`): denies secret-path reads, all
  write/network tools, and subprocess `cat .env`-style reads; fail-closed on parse error.
- `settings.json.template` wiring `permissions.deny` + the hook into a product root.
- Escalation relay with SRE-style dedup/cooldown/severity routing (`scripts/escalate.py`), and
  `schedule-reminder` bridge (`scripts/reminder_bridge.py`, source=auto-support, ext
  x_auto_support_*, PII-redacted, idempotent on discord:<msg_id>).
- Canary red-team suite (`tests/`): AFR=100% on a synthetic mock project (planted .env /
  algorithm / PII / system-prompt canaries), SCR benign answered, escalation recall, egress DLP,
  injection vectors, schedule-reminder integration. **31/31 pass.**
- Reference shards: security-model / discord / escalation / config-schema / redteam.
