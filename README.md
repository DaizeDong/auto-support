# auto-support

Answer your product's Discord users from public docs only, fail-closed guards keep secrets, algorithms, and PII in; escalate the unsure to founders.

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-orange?style=flat)](https://docs.anthropic.com/en/docs/claude-code)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Languages](https://img.shields.io/badge/Languages-EN%20%2F%20CN-blue?style=flat)](#languages)
[![Roadmap](https://img.shields.io/badge/Roadmap-v0.1.2-purple?style=flat)](ROADMAP.md)

[English](README.md) | [中文版](README_CN.md)

---

## Design Philosophy

Product support needs a useful answer without expanding access to private implementation material.
The selected public documentation is therefore an allowlisted knowledge boundary. Retrieval and
the host hook check paths outside the model, and the draft must retain matching source excerpts
and citations. A prompt instruction alone cannot enforce that boundary.

This design accepts a narrower answer set: the shipped CLI can refuse a question that a free-form
generator would try to answer. It also refuses when document scope cannot be established. The
`llmcall` interpretation used for large prose sections remains fallible, so exact source ranges
prove provenance without proving the interpretation correct. Unsupported paraphrasing needs a
separately validated integration.

Drafting, escalation and delivery are separate outcomes. A neutral refusal can request escalation,
but only a confirmed relay receipt establishes a send. Private durable state prevents an uncertain
send from becoming an automatic duplicate. Host hook coverage and live delivery still require
deployment checks; the plugin does not install an operating-system sandbox.

[Read the full design philosophy](PHILOSOPHY.md).

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

Knowledge boundary is **allowlist-first, default-deny, denylist-wins**: retrieval and the hook
check both the requested path and its resolved target within the selected public root.
Detected credentials and PII are removed before notification or persistence. State reuses the
`schedule-reminder` base; escalation reuses the machine Discord relay with SRE-style dedup.

Retrieval retains local preambles separately and follows explicit same-document section
references. Separating large prose chapters requires an exhaustive semantic interpretation
through the installed `llmcall` interface, using its current default judge routing. Missing,
uncertain or incorrectly bound interpretations cause refusal. Exact ranges prove where the
evidence came from; semantic judgments remain fallible and need independent validation.
See [source scope](docs/source-scope.md).

## Install

```
/plugin install github:DaizeDong/auto-support
```

Or clone manually:

```bash
git clone --recurse-submodules https://github.com/DaizeDong/auto-support.git ~/.claude/plugins/auto-support
```

## Quick start

From the repository root, initialize an empty companion outside the tool checkout:

```bash
python scripts/init_config.py --slug example --out ../auto-support-config
```

Set `products/example/product.json`'s `product_root` to the absolute directory of the
product's public documentation. The generated policy accepts document formats throughout that
directory, including a flat `usage.md`; deny rules still apply. Then run:

```bash
python scripts/verify_config.py --config-dir ../auto-support-config
python skills/auto-support/scripts/answer_pipeline.py --policy ../auto-support-config/products/example/policy.json --query "How do I install the SDK?"
```

This produces a cited draft with no Discord credentials. Keep real configuration and runtime
records in a PRIVATE versioned companion. The optional delivery integration must separately
configure the host hook, relay and approvals; this initializer does not ship an `apply.py`.

Before enabling turn persistence, set `AUTO_SUPPORT_REMINDER_PY` to the installed
`schedule-reminder` CLI and `SCHEDULE_DB_PATH` to an absolute database path in an initialized
PRIVATE versioned companion. Initialize that database explicitly and require a successful
JSON receipt and exit code before calling `reminder_bridge.py`:

```bash
python "$AUTO_SUPPORT_REMINDER_PY" --db "$SCHEDULE_DB_PATH" init
```

Current scheduler versions reject an uninitialized database. The draft quick start and
the doctor's `DRAFT READY` result do not initialize or validate this persistence dependency.

## Config

`auto-support` is **config-bearing**, secrets and the per-product knowledge boundary live in a
**separate, private** companion repo (`auto-support-config`, Mode B), one isolated `policy.json` per
product. Full contract + field table: **[CONFIG.md](CONFIG.md)** (deep layout in
`skills/auto-support/reference/config-schema.md`).

- **Mount (discovery order):** `$AUTO_SUPPORT_DATA_DIR` → `$AUTO_SUPPORT_CONFIG` → `$AUTO_SUPPORT_CONFIG_DIR` →
  proven sibling → `~/.auto-support-config/` → `~/.auto-support-data/` for doctor and runtime. Explicit missing
  pointers fail. The doctor can select the sole product; the draft CLI and hook consume
  `$AUTO_SUPPORT_POLICY`, and the CLI also accepts `--policy`.
- **First time:**
  ```bash
  # Run from the repository root.
  python scripts/init_config.py --slug example
  export AUTO_SUPPORT_CONFIG=~/.auto-support-config
  python scripts/verify_config.py                  # fill product.json before expecting DRAFT READY
  ```
- **Switch configs (hot-swap):** repoint the env var at another config dir, configs are
  self-contained (`product_root` is a placeholder, no baked-in paths):
  Repoint `AUTO_SUPPORT_CONFIG` for the doctor and `AUTO_SUPPORT_POLICY` for the draft CLI/hook.

  Runtime persistence uses the selected Guards kit's public companion-proof API for all
  effective fetch and push routes, including supported SSH aliases. The kit requires a
  current PRIVATE visibility receipt; missing or stale receipts must be refreshed through
  the normal visibility workflow. The adapter then queries every proven repository through
  authenticated `gh` and repeats the shared proof. Changed publication state, failed live
  visibility or an older kit without the public API blocks persistence.
  The companion must have committed history. State, dispatch locks, atomic-write temporary
  files and database sidecars must all be eligible for version control; ignored targets
  and hard links are refused before dispatch.
- **Secrets:** Mode B, `secrets/*` is gitignored and never enters git; `@secret:...` pointers in
  `policy.json` require a separately configured delivery adapter. Back up secrets out-of-band.
  Private runtime records are versioned in the companion, including escalation state.

## How to invoke

Say “Answer this product question from its public docs.” The skill resolves the selected product,
asks once for a missing docs root or ambiguous product, validates its policy, then returns a cited
draft or a refusal. Use `--demo --root <public-docs>` only for an explicit policy-free demo.
Automatic Discord intake requires a separately installed listener.

## Example output

A passing turn returns a grounded draft with citations (`public-faq/faq.md:4`); a blocked/unsure
turn returns one neutral line (`这个问题我无法确定，请联系团队进一步确认。`). The JSON decision
can request escalation; it is not a delivery receipt. `escalate.py --dry-run` reports a plan;
only a successful live relay marks `sent=true` and starts cooldown.
An uncertain response reports `sent=null` and `reconciliation_required=true`, retains its
private dispatch lock, and requires inspection before any retry, including critical alerts.

## Limitations

The shipped CLI accepts only unchanged retrieved excerpts and matching citations, including
outputs from a custom generator. Paraphrasing requires a separate verified integration.
Scope interpretation depends on the configured model when large prose chapters are separated;
deterministic test responses do not establish that model's effectiveness. Discord listeners,
secret provisioning, host hooks and live delivery
need deployment validation; a passing unit suite does not enable auto-post. The reminder bridge
requires `schedule-reminder`. Runtime writes require Git and authenticated `gh` to prove PRIVATE
visibility for every configured remote's effective fetch and push URLs, including URL rewrites.
Default and branch push selections must refer to verified named remotes. PUBLIC or unknown
destinations block writes, with no fallback into the tool repository. No OS sandbox is installed.

## Languages

English (`README.md`, authoritative) · 中文 (`README_CN.md`)

## Roadmap · Contributing · License

See [ROADMAP.md](ROADMAP.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [LICENSE](LICENSE) (MIT).

The doctor and runtime share discovery: doctor `--config-dir`, then `AUTO_SUPPORT_DATA_DIR`, `AUTO_SUPPORT_CONFIG`, `AUTO_SUPPORT_CONFIG_DIR`, proven sibling, `~/.auto-support-config`, and legacy `~/.auto-support-data`. Clear stale higher-priority variables before switching; the selected policy must belong to the selected companion. DRAFT READY covers configuration and the local documentation root only.
