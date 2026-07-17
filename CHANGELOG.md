# Changelog

All notable changes to this project are documented here (Keep a Changelog style).

## [0.1.2] - 2026-07-06
### Security (leak-critical, from adversarial review that leaked end-to-end)
- **egress DLP: ascii85 channel closed.** `_b85_views` matched only the RFC1924 alphabet, so an
  Adobe-ascii85 blob containing `:` `"` `,` `.` `/` `[` `\` `]` (all valid a85 chars) was never
  decoded/scanned, a secret emitted as ascii85 slipped the final DLP gate (reproduced end-to-end:
  a canary ascii85-embedded in a grounded sentence reached the user). Now matches any printable-
  non-space run and runs both a85/b85 decoders.
- **egress DLP: short-payload channel closed.** `_decode_layers` required a >=16-char base64 blob,
  so base64 of a short secret/PII (an SSN -> 15 pre-pad chars) bypassed decode+scan. Threshold
  lowered to 8 (decoded non-payloads are gibberish that match no credential SHAPE -> no false block).
- **PreToolUse hook: fail-OPEN tail closed.** The hook ended with an unconditional `allow()` for any
  unrecognized tool name and empty payload, contradicting its own "unknown tool => deny" contract ,
  a file-reading/shell tool under a non-standard name (e.g. `ReadFile`, `Shell`) or an empty payload
  was waved through. Now default-DENY unknown tools + empty payloads; only an explicit low-risk
  built-in allowlist (TodoWrite/TodoRead) passes. Known dangerous tools were already covered.
- +8 regression tests (`tests/test_leak_hardening.py`); no benign over-block. 105 passed.
### Notes
- Known lower-severity headroom (unchanged, tracked): multi-turn `turn_risk`/`conversation_risk` and
  `spotlight` are implemented+tested but not yet wired into the live `handle()` path; escalation/
  state-persistence are separate CLIs the model invokes (per SKILL.md), not deterministic in handle().

## [0.1.1] - 2026-06-27
### Changed
- **Discord egress unified through Agent Center relay**: pushes now prefer schedule-reminder's
  `relay.py send --stream support` (per-stream identity in the Agent Center server) when the base
  is installed, and **fall back to the Big Brother relay (send.py) when it is not**, fully
  pluggable, no behaviour change when the base is absent. Existing env/arg overrides still win.

## [0.1.0] - 2026-06-25
### Added
- Initial release, leak-safe product Discord support answering (skill-as-plugin).
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
