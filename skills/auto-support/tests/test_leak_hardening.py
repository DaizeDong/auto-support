#!/usr/bin/env python3
"""Regression guard for v0.1.2 leak-hardening (from the adversarial review that leaked end-to-end).

egress DLP: an ascii85 blob containing ':' (and other a85-only chars) bypassed _b85_views; a SHORT
base64 secret/PII (< the old 16-char threshold) bypassed _decode_layers. Both must now be caught.
PreToolUse hook: an unknown tool name (e.g. "ReadFile"/"Shell") and an empty payload hit a fail-OPEN
allow() tail; both must now be denied (exit 2).
"""
import base64
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import guardrails as G  # noqa: E402

_SSN = b"123-45-6789"  # flagged as PII in raw form; used as a decodable payload across channels
HOOK = os.path.join(SCRIPTS, "pretooluse_hook.py")


def _leaks(text):
    return bool(G.egress_leak_verdict(text))


def test_raw_pii_is_flagged_baseline():
    assert _leaks(_SSN.decode())


def test_short_base64_pii_is_caught():
    blob = base64.b64encode(_SSN).decode()          # 'MTIzLTQ1LTY3ODk=' (15 pre-pad, < old 16 gate)
    assert _leaks("here you go " + blob)


def test_ascii85_secret_with_special_chars_is_caught():
    blob = base64.a85encode(_SSN).decode()          # ascii85 alphabet includes ':' '"' '/', etc.
    assert _leaks("ref " + blob + " thanks")


def test_base85_secret_is_caught():
    blob = base64.b85encode(_SSN).decode()
    assert _leaks("code " + blob)


def _hook(payload_str):
    p = subprocess.run([sys.executable, HOOK], input=payload_str, capture_output=True, text=True)
    return p.returncode


def test_hook_denies_unknown_read_tool():
    assert _hook(json.dumps({"tool_name": "ReadFile", "tool_input": {"file_path": ".env"}})) == 2


def test_hook_denies_unknown_shell_tool():
    assert _hook(json.dumps({"tool_name": "Shell", "tool_input": {"command": "cat .env"}})) == 2


def test_hook_denies_empty_payload():
    assert _hook("") == 2


def test_hook_still_allows_legit_read_and_todo():
    assert _hook(json.dumps({"tool_name": "Read", "tool_input": {"file_path": "README.md"}})) == 0
    assert _hook(json.dumps({"tool_name": "TodoWrite", "tool_input": {}})) == 0
