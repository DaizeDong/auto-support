# Contributing to auto-support

Changes must preserve the public-document boundary and follow the requirements below.
The rationale and evidence limits are in [PHILOSOPHY.md](PHILOSOPHY.md).

## Non-negotiables for any change
1. **Never weaken a guard.** Add the missing guard or fix the bug; do not relax a threshold or
   delete a denylist entry.
2. **Guards stay outside the prompt.** New protections go in `scripts/` + `settings.json`/hook, not
   in SKILL.md prose.
3. **No secrets, ever.** No real keys/tokens/PII in code, examples or commits. Config secrets are Mode B (gitignore + DPAPI) in `auto-support-config`.

## Versioning
Bump all four sources in lock-step (`plugin.json`, both README roadmap badges, `ROADMAP.md`
Current, `CHANGELOG.md`) and re-run `check_conformance.py`.
