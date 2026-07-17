# Per-product config (`auto-support-config`, private, Mode B)

Each product gets an isolated policy; products never share a policy or read each other's files.
The skill is generic; the secrets and the boundary live in the companion config repo.

## Layout
```
products/<slug>/
  product.json              # repo root path / Discord guild id / docs URL
  policy.json               # the security policy (schema below)
  allowlist.txt denylist.txt# machine-readable globs (hook consumes denylist.txt)
  confidential-inventory.md # human ledger of secrets  -> GITIGNORED, only .template committed
  escalation.json           # escalation rules + founder channel pointer
secrets/                    # Mode B: gitignore + DPAPI ciphertext (Discord token, webhook, LLM key)
scripts/ apply.py capture-key.ps1 verify.sh functional-test.py
metrics/                    # audit ledger; only SCHEMA.md committed (*.jsonl has PII -> ignored)
runbooks/ secret-rotation.md new-machine.md incident-response.md
```

## policy.json (core fields)
```jsonc
{
  "schema_version": 1,
  "product_slug": "tokenreply",
  "product_root": "<PRODUCT_ROOT>",         // placeholder; per-machine path resolved by apply.py (self-contained, E5)
  "index_allowlist": ["README*","docs/**","public-faq/**","CHANGELOG*","examples/**","**/*.example"],
  "secret_denylist": ["**/.env","**/.env.*","*.pem","*.key","id_rsa","secrets/**","credentials/**",
                      "vault/**","src/**","internal/**","proprietary/**","algorithms/**",
                      "**/customer_data/**","**/*.pii.*","**/CLAUDE.md",".git/**"],
  "confidence": { "retrieval_min":0.7,"faithfulness_min":0.7,"high_band":0.9,"self_consistency_samples":3 },
  "escalation": { "founder_channel":"@secret:...","relay_cmd":"the notifier",
                  "dedup_window_sec":14400,"group_wait_sec":30,
                  "critical_topics":["suspected_leak","credential_hit","injection"] },
  "reply_mode": "draft_human_review",        // draft_human_review | relay_only | (later) auto_post
  "approver_user_ids": ["@secret:..."],
  "discord": { "guild_id":"...","intents":["Guilds","GuildMessages"],
               "support_channels":["@secret:..."],"trigger":["mention","reply","support_channel"] },
  "schedule_reminder": { "source":"auto-support","db_path":"@secret:..." }
}
```
`@secret:...` are pointers; real values come from DPAPI ciphertext in `secrets/` and are injected
by `apply.py` (which refuses to substitute a missing placeholder, mechanism, not memory).

## Mode B hard rules
Discord bot token / relay webhook / any LLM key -> Mode B (gitignore + DPAPI). These are in the
GitHub Secret-Scanning Partnership and get auto-revoked even in private repos. `.gitignore` covers
`secrets/*` (keep `*.template`), `products/*/confidential-inventory.md` (keep `.template`),
`metrics/**/*.jsonl`. Never echo a secret; hand login/publish to the user.

## How the skill consumes it
`pretooluse_hook.py` and `retrieval.py`/`answer_pipeline.py` read `index_allowlist` /
`secret_denylist` from `policy.json` via `$AUTO_SUPPORT_POLICY`. `apply.py` composes the product
root's `.claude/settings.json` from `templates/settings.json.template` + the resolved policy.
