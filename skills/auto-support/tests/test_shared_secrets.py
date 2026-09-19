"""The egress gate consumes the shared rules and keeps failure blocking."""
import guardrails as guards
from fleet_guards import secrets


def test_low_entropy_new_family_is_blocked():
    assert guards.scan_secrets('npm_' + 'A' * 36).hit


def test_shared_scan_failure_blocks_without_sensitive_fingerprint(monkeypatch):
    def failed(text, policy, **kwargs):
        assert policy == 'support-egress-v1'
        return {'state': 'scan_failed', 'findings': [], 'error_code': 'scanner_error'}
    monkeypatch.setattr(secrets, 'scan', failed)
    result = guards.scan_secrets('ordinary public documentation')
    assert result.hit
    assert result.names() == ['scanner_error']
    assert all(item.fingerprint == 'redacted' for item in result.findings)
