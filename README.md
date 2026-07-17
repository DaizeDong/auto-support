# auto-support

Answer your product's Discord users from public docs only, fail-closed guards keep secrets, algorithms, and PII in; escalate the unsure to founders.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.2-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## ⭐ Read this first, the design philosophy

A support bot that reads your product's repo is one prompt away from leaking your company. So the
governing principle is blunt: **its first job is to keep secrets in, not to answer.** Better to
miss an answer than to leak once. Crucially, a guard *written into a prompt* is a suggestion the
model can ignore (AWS baseline: told-not-to leaked 3/3; one deterministic hook -> blocked 3/3) ,
so every guarantee here lives **outside** the model: `permissions.deny` + a fail-closed
`PreToolUse` hook + stdlib detection + an egress DLP gate. The model literally cannot open a
secret file, so it cannot leak one.

📜 **[Read the full design philosophy -> PHILOSOPHY.md](PHILOSOPHY.md)**

---

## What it is (and isn't)

**Is:** a Claude Code plugin you deploy into a product's repo root `.claude/` to answer that
product's Discord users from its **public** docs, with deterministic leak guards and
founder-escalation when unsure. MVP replies are human-reviewed drafts / relay, not auto-posted.

**Isn't:** a general chatbot, a code explainer, or anything that reads source/secrets to "be
helpful". Out-of-allowlist questions are refused and escalated, never answered from memory.

## How it works, four fail-closed gates

```
Discord msg ─▶ entry (injection+intent, spotlighted) ─▶ retrieval (allowlist only, secret-scrubbed)
            ─▶ grounding (retrieval-conf × faithfulness) ─▶ egress (schema + DLP + canary + citation)
            ─▶ draft ─▶ founder review ─▶ approve ─▶ user      (any gate fails ⇒ neutral refusal + escalate)
```

Knowledge boundary is **allowlist-first, default-deny, denylist-wins**: secrets are never opened,
so they cannot be assembled into an answer. State (FAQ/pending/escalated) reuses the
`schedule-reminder` base; escalation reuses the machine Discord relay with SRE-style dedup.

## Install

```
/plugin install github:DaizeDong/auto-support
```

Or clone manually:

```bash
git clone https://github.com/DaizeDong/auto-support.git ~/.claude/plugins/auto-support
```

## Quick start

1. Create a private `auto-support-config` from the schema in `reference/config-schema.md`; set
   `product_root`, `index_allowlist`, `secret_denylist`, founder channel (Discord token via DPAPI).
2. `apply.py` composes the product root's `.claude/settings.json` from
   `skills/auto-support/templates/settings.json.template` (deny globs + PreToolUse hook).
3. Run the red-team gate before any non-draft reply mode: `cd skills/auto-support && python -m pytest tests/ -q`.

## Config

`auto-support` is **config-bearing**, secrets and the per-product knowledge boundary live in a
**separate, private** companion repo (`auto-support-config`, Mode B), one isolated `policy.json` per
product. Full contract + field table: **[CONFIG.md](CONFIG.md)** (deep layout in
`skills/auto-support/reference/config-schema.md`).

- **Mount (discovery order):** `$AUTO_SUPPORT_CONFIG` → `$AUTO_SUPPORT_CONFIG_DIR` →
  `~/.auto-support-config/` → `~/.config/auto-support-config/`. First that exists wins; absent ⇒ the
  hook falls back to its built-in deny defaults (fail-closed). The active product is selected by
  `$AUTO_SUPPORT_POLICY` (path to `products/<slug>/policy.json`) or the sole product.
- **First time:**
  ```bash
  cd skills/auto-support
  python scripts/init_config.py --slug <product>   # stamp a conformant skeleton (deterministic)
  export AUTO_SUPPORT_CONFIG=~/.auto-support-config
  python scripts/verify_config.py                  # doctor: PASS/FAIL, names what is missing
  ```
- **Switch configs (hot-swap):** repoint the env var at another config dir, configs are
  self-contained (`product_root` is a placeholder, no baked-in paths):
  `export AUTO_SUPPORT_CONFIG=~/configs/product-a` ↔ `~/configs/product-b`.
- **Secrets:** Mode B, `secrets/*` is gitignored and never enters git; `@secret:...` pointers in
  `policy.json` are injected from DPAPI ciphertext by the config repo's `apply.py`. Back up out-of-band.

## How to invoke

Deployed as a plugin; runs per Discord message via `scripts/answer_pipeline.py` (or `/auto-support
<msg>` headless). Triggers on @mention / reply-to-bot / a designated support channel only.

## Example output

A passing turn returns a grounded draft with citations (`public-faq/faq.md:4`); a blocked/unsure
turn returns exactly one neutral line (`这个问题我无法确定，已转交团队跟进。`) and pages the founder.

## Limitations

MVP is draft/relay (no auto-post until the red-team suite passes on the real product). No vector
store yet (precise Read/Grep grounding). On bare Windows there is no OS sandbox layer, run under
WSL2/devcontainer for full defense depth. The full faithfulness judge LLM is an integration seam.

## Languages

English (`README.md`, authoritative) · 中文 (`README_CN.md`)

## Roadmap · Contributing · License

See [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE) (MIT).
