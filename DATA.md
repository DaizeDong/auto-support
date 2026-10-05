# Private support data

[storage.contract.json](storage.contract.json) declares companion paths and retention.
[CONFIG.md](CONFIG.md) and `skills/auto-support/scripts/policy.py` remain the authority
for policy fields, product selection and validation.

The PRIVATE companion keeps `registry.json` and each current product's
`product.json` and `policy.json`. The JSON policy is the enforcement input.
Generated allow/deny text exports and blank inventory templates are rebuildable
references; remove them when they no longer serve setup or review. Keep a real
inventory only when someone uses it to review the current deny policy.

`data/escalation_state.json` records delivery fingerprints, timestamps and severity.
Keep it while dispatch, cooldown or reconciliation depends on it. An uncertain
delivery is not safe to retry merely because a local state file was removed.
Locks and temporary files require confirming the writer and commit outcome before
cleanup. Custom state paths need a corresponding contract entry.

Credential references stay in policy; credential bytes remain in the approved
private credential store or backup. A saved reference does not provision a
delivery integration. The draft CLI and doctor require no delivery credentials.
Use the current source doctor, `scripts/verify_config.py`, for draft readiness;
old companion installation scripts are not part of this storage contract.

Keep only current configuration, needed state and selected evidence. Source
documentation owns schemas and operating rules; the companion README links here.
Use skill-smith's shared `storage_contract.py` to validate the contract and inspect
a verified PRIVATE companion. That checker inventories paths and bytes; domain
validation and delivery evidence remain separate. Removal needs an explicitly
reviewed inactive selection, and does not erase Git history.
