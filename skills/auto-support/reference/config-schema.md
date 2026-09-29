# Per-product configuration

The authoritative field table and runnable initialization commands are in
[`CONFIG.md`](../../../CONFIG.md). Run `scripts/init_config.py` and `scripts/verify_config.py`
from the repository root. Runtime validation is shared through `scripts/policy.py` in this skill.

A generated companion contains:

```text
registry.json
products/<slug>/product.json
products/<slug>/policy.json
products/<slug>/allowlist.txt
products/<slug>/denylist.txt
products/<slug>/confidential-inventory.md.template
secrets/README.md
metrics/SCHEMA.md
```

Fill the machine's public-docs root in product.json. Keep the policy's `<PRODUCT_ROOT>`
placeholder to let the CLI resolve that root. The two text lists are reference exports;
JSON is the enforcement source. Adding a product preserves existing entries.

Real configuration, inventories and runtime records belong in the PRIVATE versioned companion.
Credentials under secrets/ remain excluded from Git. The initializer supplies no `apply.py`,
Discord listener or credential capture helper. Those are separately validated deployment
integrations; the default supported first-run path returns a local draft.
