# auto-support

Draft cited answers to product questions from public documentation, with path and content checks and escalation requests for unsupported questions.

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

## Scope

This Claude Code plugin supports product Discord questions through public-document retrieval,
cited drafts and founder review or relay. It is deployed through the product root's `.claude/`
configuration. The shipped CLI returns local drafts; it does not automatically post replies.

Questions requiring source code, secrets or other material outside the public allowlist are
refused and referred for review. General conversation and code explanation are outside this scope;
missing evidence cannot be replaced with answers from memory.

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

## Config

Store per-product configuration and runtime records in a separate PRIVATE versioned
`auto-support-config` companion. Each product has its own `policy.json`.
[CONFIG.md](CONFIG.md) owns discovery order, policy selection, initialization and switching;
[the schema reference](skills/auto-support/reference/config-schema.md) describes the layout.

When switching companions, clear stale higher-priority selectors and update both the doctor/state
selection and `AUTO_SUPPORT_POLICY` for the draft CLI and hook. The policy must belong to the
selected companion. `DRAFT READY` covers configuration and the local documentation root only.

The current credential setup uses Mode B: `secrets/*` is excluded from Git and credentials need
an approved separate backup. Runtime records, including escalation state, remain versioned.
Optional `@secret:...` references require a separately configured delivery adapter.

Before persisting a turn, follow [reminder setup](CONFIG.md#reminder-persistence-setup) to select
and initialize a PRIVATE scheduler database. Follow [DATA.md](DATA.md) for state retention and
recovery; uncertain delivery locks must remain until the outcome is reconciled.

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
