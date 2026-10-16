# auto-support, Config

Configuration and real runtime records live in a separate PRIVATE `auto-support-config`
repository (Mode B). The public tool ships an empty initializer and synthetic tests.
`skills/auto-support/scripts/policy.py` owns the policy schema used by init, doctor, hook and CLI.

## Discovery and selection (E2)

The doctor uses `--config-dir`, then the shared runtime order: `AUTO_SUPPORT_DATA_DIR`,
`AUTO_SUPPORT_CONFIG`, then a proven sibling companion. There is no
home-directory location. A selected `data` child resolves
to its companion root for settings. An explicit invalid directory
fails; it does not select a different config. Product selection uses `--policy`, then
`AUTO_SUPPORT_POLICY`, then `--slug`, then the sole product. Multiple products require a selector.

The draft CLI takes `--policy` or `AUTO_SUPPORT_POLICY`; the hook uses `AUTO_SUPPORT_POLICY`.
An explicit missing, malformed or incomplete policy fails before answering or permitting a read.
Without a policy the hook binds its restricted project-layout globs to its process working
directory. The CLI requires `--demo --root <project-root>` for that demonstration mode;
its built-ins allow README, docs, public-faq, examples and example files. Demo cannot override
a supplied policy. Normal initialization instead uses document-format globs suited to a
dedicated public-docs directory, including flat files.

Hook requests resolve relative paths against the absolute event `cwd` and must stay within
the selected root before and after resolving links. `Grep` and `Glob` require an explicit
`path`; directory searches are rejected if any reachable file is outside the public policy.
Shell reads accept only the small literal grammar in the hook, with no expansions or pipelines.

Real escalation state uses the fleet_guards package's companion discovery. Set `AUTO_SUPPORT_CONFIG`
to the private companion or `AUTO_SUPPORT_DATA_DIR` to its existing data directory.
`--state-path` may only select a location within that data
directory. An unresolved companion fails before dispatch; there is no unversioned or in-repo
fallback. The runtime checks are path-only and start no Git or `gh` process: the destination
must sit inside a Git worktree that is not this tool tree, with no parent traversal, `.git`
components, alternate streams, links or hard links. Repository visibility is not checked at
runtime; the commit and push hooks enforce PRIVATE publication of the companion.

The optional reminder bridge requires `--db` or `SCHEDULE_DB_PATH` to select an absolute
database path in the companion worktree. It checks the database and SQLite sidecars before
every writing CLI invocation. An unset path, a path outside any Git worktree, a nested
repository or a hard link stops before persistence. The bridge does not inherit a database
default from the reminder installation.

## Schema (E1)

| File or field | Contract |
|---|---|
| `registry.json` | `schema_version: 1`, `mode`, `spec`, and product slug list |
| `products/<slug>/product.json` | Matching `slug`, status `draft` or `active`, absolute existing `product_root` |
| `policy.schema_version` | Integer `1` |
| `policy.product_slug` | Lowercase kebab-case slug matching product.json |
| `policy.product_root` | `<PRODUCT_ROOT>` resolved from product.json, or an explicit absolute directory |
| `index_allowlist`, `secret_denylist` | Nonempty lists of nonempty path globs; deny wins |
| `confidence` | Numeric `retrieval_min`, `faithfulness_min`, `high_band` in 0..1; high band at least both minima |
| `reply_mode` | `draft_human_review`, `relay_only` or `auto_post`; the shipped CLI always returns a draft |
| `escalation`, `discord` | Objects for a separately provisioned delivery integration |
| `@secret:...` | References to credentials, never literal secret values |

The generated `allowlist.txt` and `denylist.txt` are reference exports. Runtime policy is read
from JSON; changing an export does not change enforcement. `self_consistency_samples` and
Discord fields describe optional integrations and do not enable those capabilities.

## First-time setup (E3/E4)

Run these commands from the public tool repository root. The output must be outside it:

```bash
python scripts/init_config.py --slug example --out ../auto-support-config
```

Set `products/example/product.json`'s `product_root` to the absolute directory of public docs.
Then validate and generate a draft:

```bash
python scripts/verify_config.py --config-dir ../auto-support-config
python skills/auto-support/scripts/answer_pipeline.py --policy ../auto-support-config/products/example/policy.json --query "How do I install the SDK?"
```

The initializer creates registry, product, policy, reference exports, an inventory template,
metrics schema and secret exclusions. Re-running preserves existing files; adding a product
merges its slug into the registry. `--force` overwrites the selected product's files, so use it
only to intentionally reset those templates. Malformed existing registries fail before writing.
No `apply.py`, secret-capture helper or Discord listener is generated.

`DRAFT READY` means configuration and local documentation root checks passed. It does not mean
the host hook, public-document freshness, Discord transport or a semantic judge was tested.

### Reminder persistence setup

Set `AUTO_SUPPORT_REMINDER_PY` to the installed `schedule-reminder` CLI and
`SCHEDULE_DB_PATH` to an absolute database path in an initialized PRIVATE versioned companion.
Initialize it explicitly before calling `reminder_bridge.py`:

```bash
python "$AUTO_SUPPORT_REMINDER_PY" --db "$SCHEDULE_DB_PATH" init
```

Require both a successful JSON receipt and exit code. Current scheduler versions reject an
uninitialized database; draft setup and `DRAFT READY` do not initialize or validate this dependency.
The [escalation reference](skills/auto-support/reference/escalation.md#reminder-persistence)
defines receipt validation, replay and transition behavior.

## Private data and secrets (E6)

Version policies, non-secret product configuration, inventories and actual runtime records in
the PRIVATE companion. `secrets/*`, environment files and credential files remain gitignored;
back up credentials separately. Never copy production records into public examples or fixtures.

## Switching products (E5)

Clear `AUTO_SUPPORT_DATA_DIR` before switching.
Point `AUTO_SUPPORT_CONFIG` at the new companion for doctor and state discovery, and
`AUTO_SUPPORT_POLICY` at its selected product policy for CLI and hook. Run the doctor against
each configuration after filling its root. `--root`, when supplied to the draft CLI, must match
the selected product; it cannot widen the policy to a different directory.

## README integration (E7)

Both README language editions include the same runnable draft setup and Config section.
The detailed delivery boundary is in `skills/auto-support/reference/escalation.md`.
