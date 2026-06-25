# Contributing to auto-support

This is a security-critical skill. The bar is **proven, not declared** (PHILOSOPHY P5).

## Non-negotiables for any change
1. **Run the red-team gate and keep it green:** `cd skills/auto-support && python -m pytest tests/ -q`.
   AFR must stay 100% (zero canary leaks); SCR must stay >= 95%. A change that lowers AFR is rejected.
2. **Never weaken a guard to pass a test.** Add the missing guard or fix the bug; do not relax a
   threshold or delete a denylist entry to make red-team pass.
3. **Guards stay outside the prompt.** New protections go in `scripts/` + `settings.json`/hook, not
   in SKILL.md prose.
4. **No secrets, ever.** No real keys/tokens/PII in code, tests, fixtures (use `*_CANARY` markers),
   or commits. Config secrets are Mode B (gitignore + DPAPI) in `auto-support-config`.
5. **New attack class -> new regression test first.** Add the failing red-team case, then the guard.

## Adding a red-team vector
Put attacks + benign decoys in `tests/test_pipeline_redteam.py`; plant any new canary in
`tests/fixtures/mock-project/` and register it in `tests/conftest.py::CANARIES` (the independent judge).

## Versioning
Bump all four sources in lock-step (`plugin.json`, both README roadmap badges, `ROADMAP.md`
Current, `CHANGELOG.md`) and re-run `check_conformance.py`.
