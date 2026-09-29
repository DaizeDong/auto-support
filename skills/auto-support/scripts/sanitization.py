"""Shared secret-and-PII redaction before notification or persistence."""
import guardrails as G


def redact(text):
    text = text or ""
    findings = G.scan_secrets(text).findings + G.scan_pii(text).findings
    spans = []
    for finding in sorted(findings, key=lambda f: f.span):
        start, end = finding.span
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]), "SENSITIVE")
        else:
            spans.append((start, end, finding.rule.upper()))
    for start, end, rule in reversed(spans):
        text = text[:start] + "[REDACTED_" + rule + "]" + text[end:]
    return text


def sanitize_fields(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: sanitize_fields(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_fields(item) for item in value]
    return value
