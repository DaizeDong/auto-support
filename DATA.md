# Private support data

[storage.contract.json](storage.contract.json) declares paths relative to the exact
PRIVATE companion worktree root and their retention. It covers the full companion,
including setup metadata; a `data` directory alone is not the inventory root.
[CONFIG.md](CONFIG.md) and `skills/auto-support/scripts/policy.py` remain the authority
for policy fields, product selection and validation.

The PRIVATE companion keeps `registry.json` and each current product's
`product.json` and `policy.json`. The JSON policy is the enforcement input.
Generated allow/deny text exports and blank inventory templates are rebuildable
references; remove them when they no longer serve setup or review. Keep a real
inventory only when someone uses it to review the current deny policy.

The runtime resolver uses an existing companion `data` directory when present and
otherwise selects the companion root. Its default state is therefore
`data/escalation_state.json` or `escalation_state.json`, respectively. Both exact
state paths and their adjacent lock and replacement files are declared. State
records delivery fingerprints, timestamps and severity.
Keep it while dispatch, cooldown or reconciliation depends on it. An uncertain
delivery is not safe to retry merely because a local state file was removed.
Locks and temporary files require confirming the writer and commit outcome before
cleanup. Custom state paths need a corresponding contract entry.

Credential references stay in policy; credential bytes remain in the approved
private credential store or backup. A saved reference does not provision a
delivery integration. The draft CLI and doctor require no delivery credentials.
Use the current source doctor, `scripts/verify_config.py`, for draft readiness.
The exact companion `LICENSE` copy is a rebuildable reference.

The exact `runbooks/incident-response.md` procedure remains core until a reviewed
replacement covers its recovery duties and unresolved incident and delivery
outcomes are closed. Its reference to an older rotation procedure does not make
that rotation chain valid for the current integration.

Legacy `products/*/escalation.json` files are retired only after all their settings
are preserved in the matching policy and external consumers are checked. The
current source reads escalation settings from policy JSON. The exact earlier
`scripts/apply.py`, `scripts/capture-key.ps1` and `scripts/verify.sh` helpers,
`runbooks/new-machine.md`, `runbooks/secret-rotation.md`, `CHANGELOG.md` and
`PHILOSOPHY.md` are declared retired. They describe the earlier deployment flow;
the settings composer does not use the current product-root resolver and replaces
permission lists. Removal remains pending an explicit inactive selection and
replacement of remaining recovery references. Retiring a helper does not retire
credentials, their backups or unresolved delivery state.

These declarations cover only the named artifacts. Unknown paths and new incident
outputs need their own producer, consumer, schema and recovery review before they
can be treated as covered.

Keep only current configuration, needed state and selected evidence. Source
documentation owns schemas and operating rules; the companion README links here.
Use skill-smith's shared `storage_contract.py` to validate the contract and inspect
a verified PRIVATE companion. That checker inventories paths and bytes; domain
validation and delivery evidence remain separate. Removal needs an explicitly
reviewed inactive selection, and does not erase Git history.
