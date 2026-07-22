#!/usr/bin/env python3
"""Stamp a spec-conformant `auto-support-config` companion repo (config-spec E3/E4).

auto-support is config-bearing, but uses a **per-product policy** layout (Mode B), NOT the generic
`registry.json`. Each product gets an isolated `products/<slug>/policy.json`; products never share a
policy or read each other's files. This script writes an empty, conformant skeleton for one product.

Deterministic + template-driven (E4): re-running with the same --slug + --out produces byte-identical
output. Self-contained (E5): the committed policy.json carries the placeholder `<PRODUCT_ROOT>` and
`@secret:...` pointers — never a real absolute path, never a real secret. `apply.py` (in the config
repo) resolves the placeholder + injects DPAPI ciphertext at deploy time (mechanism, not memory).

Discovery convention this skill uses (also CONFIG.md §Discovery, E2). The config dir resolves from,
in order; first that exists wins:
  1. $AUTO_SUPPORT_CONFIG        (recommended; location-independent)
  2. $AUTO_SUPPORT_CONFIG_DIR    (accepted alias)
  3. ~/.auto-support-config/     (dotfile-in-home fallback)
  4. ~/.config/auto-support-config/ (XDG-style fallback)
Within the resolved config dir, the skill consumes ONE product via $AUTO_SUPPORT_POLICY pointing at
products/<slug>/policy.json (or the sole product when exactly one exists).

Usage:
  python init_config.py [--slug <name>] [--out <dir>] [--force]

--slug  product slug (kebab-case); default "example".
--out   target config-repo dir; default the discovery path ~/.auto-support-config/.
Stdlib only. Cross-platform. Never writes secrets; never echoes anything secret.
"""
import argparse
import json
import os
import sys

ENV_VAR = "AUTO_SUPPORT_CONFIG"
DEFAULT_DIR = os.path.expanduser("~/.auto-support-config")

GITIGNORE = """\
# auto-support-config — Mode B secrets gate (config-spec E6). Real values never enter git.
secrets/*
!secrets/README.md
!secrets/.gitkeep
*.env
!*.env.template
!env.template
claude.json
.claude.json
*credentials*.json
*.key
*.pem
!*.key.template
!*.pem.template

# Per-product human ledgers + audit metrics carry PII -> only the templates/schema are committed.
products/*/confidential-inventory.md
!products/*/confidential-inventory.md.template
metrics/**/*.jsonl
"""

SECRETS_README = """\
# secrets/ — Mode B (gitignored)

DPAPI ciphertext only: Discord bot token, relay webhook, any LLM key. These are in the GitHub
Secret-Scanning Partnership and get auto-revoked even in private repos, so they are **gitignored**
(see ../.gitignore) and never enter git. Capture them with `scripts/capture-key.ps1`; `apply.py`
injects them where `policy.json` has an `@secret:...` pointer (refuses to substitute a missing
placeholder — mechanism, not memory). Back up out-of-band; never echo a secret. UTF-8 without BOM.
"""

METRICS_SCHEMA = """\
# metrics/ schema

Audit ledger of each turn (PII -> only this SCHEMA.md is committed; `*.jsonl` is gitignored).

| field        | type   | meaning                                            |
|--------------|--------|----------------------------------------------------|
| ts           | string | ISO-8601 timestamp                                 |
| product_slug | string | which product policy handled the turn              |
| decision     | string | answered | refused | escalated                     |
| gate_failed  | string | entry | retrieval | grounding | egress | "" (none)|
| confidence   | number | grounding confidence 0..1                          |
| citation     | string | doc:line that grounded the answer (or "")          |
"""

CONFIDENTIAL_INVENTORY_TEMPLATE = """\
# Confidential inventory — <PRODUCT> (TEMPLATE; copy to confidential-inventory.md, which is gitignored)

Human ledger of what must NEVER leave the repo, so the denylist can be audited against reality.
One row per secret/asset class. The live copy holds real paths/owners and is gitignored.

| asset class        | example path/glob        | why confidential          | owner |
|--------------------|--------------------------|---------------------------|-------|
| credentials        | **/.env, secrets/**      | grants access             | TODO  |
| proprietary source | src/**, algorithms/**    | core IP                   | TODO  |
| customer PII        | **/customer_data/**      | privacy / legal           | TODO  |
"""


def policy_skeleton(slug):
    """Deterministic, self-contained policy.json (E4/E5): placeholder root + @secret pointers."""
    return {
        "schema_version": 1,
        "product_slug": slug,
        "product_root": "<PRODUCT_ROOT>",
        "index_allowlist": ["README*", "docs/**", "public-faq/**", "CHANGELOG*",
                            "examples/**", "**/*.example"],
        "secret_denylist": ["**/.env", "**/.env.*", "*.pem", "*.key", "id_rsa", "secrets/**",
                            "credentials/**", "vault/**", "src/**", "internal/**", "proprietary/**",
                            "algorithms/**", "**/customer_data/**", "**/*.pii.*", "**/CLAUDE.md",
                            ".git/**"],
        "confidence": {"retrieval_min": 0.7, "faithfulness_min": 0.7, "high_band": 0.9,
                       "self_consistency_samples": 3},
        "escalation": {"founder_channel": "@secret:founder_channel",
                       "relay_cmd": "~/.local/notifier.py",
                       "dedup_window_sec": 14400, "group_wait_sec": 30,
                       "critical_topics": ["suspected_leak", "credential_hit", "injection"]},
        "reply_mode": "draft_human_review",
        "approver_user_ids": ["@secret:approver_user_ids"],
        "discord": {"guild_id": "<DISCORD_GUILD_ID>", "intents": ["Guilds", "GuildMessages"],
                    "support_channels": ["@secret:support_channels"],
                    "trigger": ["mention", "reply", "support_channel"]},
        "schedule_reminder": {"source": "auto-support", "db_path": "@secret:schedule_db_path"},
    }


def product_skeleton(slug):
    return {
        "product_slug": slug,
        "product_root": "<PRODUCT_ROOT>",
        "discord_guild_id": "<DISCORD_GUILD_ID>",
        "docs_url": "<DOCS_URL>",
    }


def write(path, content, force):
    if os.path.exists(path) and not force:
        print("  SKIP (exists): %s" % path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("  wrote: %s" % path)


def main():
    ap = argparse.ArgumentParser(description="Stamp a spec-conformant auto-support-config repo.")
    ap.add_argument("--slug", default="example", help="product slug (kebab-case)")
    ap.add_argument("--out", default=None, help="config-repo dir (default ~/.auto-support-config)")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    slug = a.slug
    out = os.path.abspath(os.path.expanduser(a.out or DEFAULT_DIR))
    prod = os.path.join(out, "products", slug)

    print("Init auto-support-config (Mode B) at %s" % out)
    print("Discovery env var: %s  (alias %s_DIR, fallback %s)" % (ENV_VAR, ENV_VAR, DEFAULT_DIR))
    print("Product: %s" % slug)

    def j(obj):
        return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"

    write(os.path.join(prod, "policy.json"), j(policy_skeleton(slug)), a.force)
    write(os.path.join(prod, "product.json"), j(product_skeleton(slug)), a.force)
    write(os.path.join(prod, "allowlist.txt"),
          "\n".join(policy_skeleton(slug)["index_allowlist"]) + "\n", a.force)
    write(os.path.join(prod, "denylist.txt"),
          "\n".join(policy_skeleton(slug)["secret_denylist"]) + "\n", a.force)
    write(os.path.join(prod, "confidential-inventory.md.template"),
          CONFIDENTIAL_INVENTORY_TEMPLATE, a.force)

    write(os.path.join(out, ".gitignore"), GITIGNORE, a.force)
    write(os.path.join(out, "secrets", "README.md"), SECRETS_README, a.force)
    write(os.path.join(out, "secrets", ".gitkeep"), "", a.force)
    write(os.path.join(out, "metrics", "SCHEMA.md"), METRICS_SCHEMA, a.force)

    print("\nNext:")
    print("  1) Fill products/%s/: set <PRODUCT_ROOT> + <DISCORD_GUILD_ID> + <DOCS_URL>;" % slug)
    print("     capture secrets into secrets/ (gitignored) so each @secret:... pointer resolves.")
    print("  2) export %s=%s   (or use the default path)" % (ENV_VAR, out))
    print("     export AUTO_SUPPORT_POLICY=%s" % os.path.join(prod, "policy.json"))
    print("  3) python scripts/verify_config.py   # doctor: confirms the config is ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
