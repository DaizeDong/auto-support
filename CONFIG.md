# auto-support, Config

`auto-support` is **config-bearing**: secrets and the per-product knowledge boundary live in a
**separate, private companion repo** you create, `auto-support-config` (Mode B). The skill repo is
generic and ships no secrets. This file is the authoritative config contract (config-spec E1); the
deep field layout lives in [`skills/auto-support/reference/config-schema.md`](skills/auto-support/reference/config-schema.md).

Unlike the generic `registry.json` variant, auto-support uses a **per-product `policy.json`** so
products never share a policy or read each other's files.

## Discovery convention (how the skill finds your config), E2

The config dir resolves in this order; the first that exists wins:

1. `$AUTO_SUPPORT_CONFIG`, environment variable (recommended; location-independent).
2. `$AUTO_SUPPORT_CONFIG_DIR`, accepted alias.
3. `~/.auto-support-config/`, dotfile-in-home fallback.
4. `~/.config/auto-support-config/`, XDG-style fallback (Linux/macOS).

Within the resolved config dir the skill consumes **one** product. Product selection order:

1. `$AUTO_SUPPORT_POLICY`, absolute path to `products/<slug>/policy.json` (the hook reads this directly).
2. the sole product under `<config>/products/` when exactly one exists.

If nothing resolves, the deterministic `pretooluse_hook.py` falls back to its built-in deny defaults
(fail-closed), a missing config never widens access, only narrows what can be answered.

> Scattered runtime env vars (`$AUTO_SUPPORT_STATE_DIR`, `$AUTO_SUPPORT_REMINDER_PY`,
> `$AUTO_SUPPORT_MCP_ALLOW`, `$SCHEDULE_DB_PATH`) are optional per-machine overrides, not config
> discovery. `apply.py` derives them from the resolved policy; set them by hand only for tests.

## Schema, `products/<slug>/policy.json` (E1)

| Field | Type | Required | Example |
|---|---|---|---|
| `schema_version` | int | yes | `1` |
| `product_slug` | string | yes | `"tokenreply"` |
| `product_root` | string (placeholder) | yes | `"<PRODUCT_ROOT>"`, resolved per-machine by `apply.py`; never a baked-in absolute path (E5) |
| `index_allowlist` | string[] (globs) | yes | `["README*","docs/**","public-faq/**"]` |
| `secret_denylist` | string[] (globs) | yes | `["**/.env","src/**","secrets/**","**/CLAUDE.md"]` |
| `confidence` | object | yes | `{"retrieval_min":0.7,"faithfulness_min":0.7,"high_band":0.9,"self_consistency_samples":3}` |
| `escalation` | object | yes | `{"founder_channel":"@secret:founder_channel","relay_cmd":"the notifier","dedup_window_sec":14400,"group_wait_sec":30,"critical_topics":["suspected_leak"]}` |
| `reply_mode` | enum | yes | `"draft_human_review"` \| `"relay_only"` \| `"auto_post"` |
| `approver_user_ids` | string[] | no | `["@secret:approver_user_ids"]` |
| `discord` | object | yes | `{"guild_id":"<DISCORD_GUILD_ID>","intents":["Guilds","GuildMessages"],"support_channels":["@secret:support_channels"],"trigger":["mention","reply","support_channel"]}` |
| `schedule_reminder` | object | no | `{"source":"auto-support","db_path":"@secret:schedule_db_path"}` |

`@secret:...` are **pointers**, never plaintext. Real values are DPAPI ciphertext in `secrets/` and
are injected by the config repo's `apply.py` (which refuses to substitute a missing placeholder ,
mechanism, not memory). `<PRODUCT_ROOT>` / `<DISCORD_GUILD_ID>` / `<DOCS_URL>` are per-machine
placeholders resolved at apply time (keeps the committed policy self-contained, E5).

Companion repo layout (one isolated dir per product):

```
auto-support-config/
  products/<slug>/ policy.json product.json allowlist.txt denylist.txt
                   confidential-inventory.md.template   # live .md is gitignored
  secrets/         # Mode B: DPAPI ciphertext (Discord token / webhook / LLM key) — gitignored
  metrics/SCHEMA.md   # *.jsonl audit ledger has PII -> gitignored
  scripts/ apply.py capture-key.ps1   runbooks/
```

## Secrets, Mode B (E6)

The companion config repo is **separate and private**. Discord bot token / relay webhook / any LLM
key are Mode B: `.gitignore` blocks `secrets/*` (keep `*.template`),
`products/*/confidential-inventory.md` (keep `.template`), and `metrics/**/*.jsonl`. Real values
never enter git; back them up out-of-band. Never echo a secret; hand login/publish to the user.

## First-time setup (E3), succeeds on the first try

```bash
cd skills/auto-support

# 1. Stamp a conformant, self-contained skeleton for one product (deterministic — E4):
python scripts/init_config.py --slug <your-product>      # -> ~/.auto-support-config/  (or --out <dir>)

# 2. Point the skill at it:
export AUTO_SUPPORT_CONFIG=~/.auto-support-config
export AUTO_SUPPORT_POLICY=~/.auto-support-config/products/<your-product>/policy.json

# 3. Fill <PRODUCT_ROOT>/<DISCORD_GUILD_ID>, capture secrets into secrets/, then confirm readiness:
python scripts/verify_config.py        # doctor: PASS/FAIL per check, names what is missing
```

## Switching between configs (hot-swap), E5

A config dir is self-contained (no hardcoded paths, `product_root` is a placeholder). Keep as many
as you like and switch by repointing the env var; no other change:

```bash
export AUTO_SUPPORT_CONFIG=~/configs/product-a    # config A
export AUTO_SUPPORT_CONFIG=~/configs/product-b    # config B — same skill, different boundary
```

Verify the swap: `init_config.py --out ~/configs/product-a` and `--out ~/configs/product-b`, run
`verify_config.py` against each (flip `$AUTO_SUPPORT_CONFIG` between them), both must report READY.
