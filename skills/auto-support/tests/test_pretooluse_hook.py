# -*- coding: utf-8 -*-
"""End-to-end PreToolUse hook enforcement (closes the round-2 spec-gap: the hook was NEVER tested).

Drives the REAL hook as a subprocess exactly as Claude Code does — JSON event on stdin, exit 0 =
allow, exit 2 = block — under attacker-controlled paths and commands. These cover the two HIGH gaps
the stage-1 audit proved end-to-end (path-traversal Read; Bash fail-OPEN via interpreters / stdin
redirection) plus the existing write/net contract, so the enforcement layer can never silently
regress to fail-OPEN again.
"""
import json
import os
import subprocess
import sys

HOOK = os.path.join(os.path.dirname(__file__), "..", "scripts", "pretooluse_hook.py")


def _run(evt: dict) -> int:
    p = subprocess.run([sys.executable, HOOK], input=json.dumps(evt),
                       capture_output=True, text=True)
    return p.returncode


def _read(path):
    return {"tool_name": "Read", "tool_input": {"file_path": path}}


def _bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


# ---- HIGH-1: path-traversal Read is blocked end-to-end ----------------------------------
def test_hook_blocks_read_traversal():
    for p in ["docs/../secrets/customers.csv", "docs/../src/ranking.py",
              "docs/../internal/system.txt", "docs/%2e%2e/secrets/customers.csv",
              "docs/..\\secrets\\customers.csv"]:
        assert _run(_read(p)) == 2, p


def test_hook_blocks_read_denied_direct():
    for p in [".env", "secrets/customers.csv", "src/ranking.py", "internal/system.txt"]:
        assert _run(_read(p)) == 2, p


def test_hook_allows_read_public():
    for p in ["README.md", "docs/usage.md", "public-faq/faq.md"]:
        assert _run(_read(p)) == 0, p


# ---- HIGH-2: Bash no longer fail-OPEN (interpreters / stdin redirection / default-deny) --
def test_hook_blocks_interpreter_read():
    for cmd in [
        "python -c \"print(open('.env').read())\"",
        "python3 -c 'import io;print(io.open(\".env\").read())'",
        "node -e \"console.log(require('fs').readFileSync('.env','utf8'))\"",
        "perl -e 'open(F,\".env\");print<F>'",
        "ruby -e 'puts File.read(\".env\")'",
        "php -r 'echo file_get_contents(\".env\");'",
        "dd if=.env",
    ]:
        assert _run(_bash(cmd)) == 2, cmd


def test_hook_blocks_stdin_redirection():
    for cmd in ["tr a-z A-Z < .env", "while read line < .env; do echo $line; done",
                "cat < secrets/customers.csv"]:
        assert _run(_bash(cmd)) == 2, cmd


def test_hook_bash_default_deny_unknown():
    # an unmatched command must fail-CLOSED (the old tail waved it through with allow()).
    for cmd in ["env", "printenv DATABASE_URL", "exec cat .env", "eval 'cat .env'"]:
        assert _run(_bash(cmd)) == 2, cmd


def test_hook_allows_innocuous_bash():
    for cmd in ["echo hello", "pwd", "ls docs", "cat docs/usage.md"]:
        assert _run(_bash(cmd)) == 0, cmd


# ---- existing write / net / unknown-mcp contract stays enforced -------------------------
def test_hook_blocks_write_net_and_unknown_mcp():
    assert _run({"tool_name": "Write", "tool_input": {"file_path": "docs/x.md"}}) == 2
    assert _run({"tool_name": "WebFetch", "tool_input": {"url": "http://x"}}) == 2
    assert _run({"tool_name": "mcp__unknown__do", "tool_input": {}}) == 2
    assert _run({"tool_name": "Read", "tool_input": {}}) == 2  # no path -> fail-closed
