#!/usr/bin/env python3
"""auto-support — PreToolUse hook: the deterministic, fail-closed enforcement layer.

THIS is the guard, not SKILL.md. Claude Code runs this before every tool call and feeds it the
tool name + input on stdin. We exit 2 (block, with a stderr reason fed back to the model) the
instant a call would touch a secret path, read a denied file via a subprocess (`cat .env`),
write/delete anything, or reach the network. permissions.deny alone is bypassable (it does not
cover python/node `open()`, and issue #27040 shows deny rules can be skipped) — so the boundary
lives HERE, where it cannot be argued away.

Protocol (Anthropic hooks): stdin = JSON {tool_name, tool_input{...}}. exit 0 = allow,
exit 2 = block + stderr shown to model. fail-closed: ANY parse error / unknown tool / unreadable
policy => exit 2 (deny). Policy (allowlist/denylist) from $AUTO_SUPPORT_POLICY or built-in defaults.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrails as G  # noqa: E402

DEFAULT_ALLOW = ["README*", "docs/**", "public-faq/**", "CHANGELOG*", "examples/**", "**/*.example"]
DEFAULT_DENY = ["**/.env", "**/.env.*", "*.pem", "*.key", "id_rsa", "secrets/**", "credentials/**",
                "vault/**", "src/**", "internal/**", "proprietary/**", "algorithms/**",
                "**/customer_data/**", "**/*.pii.*", "**/CLAUDE.md", "**/.git/**"]

# Tools that read files -> path-check against the knowledge boundary.
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead"}
# Tools that mutate or exfiltrate -> always denied for a read-only support bot.
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Update"}
NET_TOOLS = {"WebFetch", "WebSearch"}

# Bash command fragments that read denied files or reach the network / mutate.
_BASH_READ = re.compile(r"\b(cat|head|tail|less|more|sed|awk|grep|rg|strings|xxd|od|base64|cp|mv|type|gc|get-content)\b", re.I)
_BASH_NET = re.compile(r"\b(curl|wget|nc|netcat|ssh|scp|ftp|telnet|invoke-webrequest|iwr|invoke-restmethod)\b", re.I)
_BASH_WRITE = re.compile(r"(>>?|\b(rm|del|mv|cp|tee|set-content|out-file|add-content)\b)", re.I)
# Interpreters / byte-tools that read arbitrary files via code or stdin, bypassing the read-tool
# path gate (`python -c open('.env')`, `node -e`, `perl/ruby/php -e`, `dd if=.env`, `tr/cut/xargs`).
# A read-only support bot has NO legitimate use for them -> fail-closed DENY.
_BASH_INTERP = re.compile(
    r"\b(python[0-9.]*|py|node|nodejs|deno|bun|perl|ruby|php|rscript|lua|"
    r"dd|tr|cut|xargs|eval|source|exec)\b", re.I)
# Input redirection `< path` (stdin read). `tr A-Z a-z < .env`, `while read < .env`. The old write
# regex only matched `>` so this read channel was invisible -> path-check the redirect target.
_BASH_INREDIR = re.compile(r"(?<![<0-9])<(?!<)\s*([^\s<>|&;]+)")
# Innocuous leading commands allowed under default-deny (still token-path-checked below).
_BASH_SAFE_LEAD = {"echo", "printf", "pwd", "ls", "dir", "cd", "true", "false", "clear", "date"}


def _load_policy():
    p = os.environ.get("AUTO_SUPPORT_POLICY")
    if p and os.path.isfile(p):
        try:
            pol = json.load(open(p, encoding="utf-8"))
            return (pol.get("index_allowlist", DEFAULT_ALLOW),
                    pol.get("secret_denylist", DEFAULT_DENY))
        except Exception:
            # fail-closed: an unreadable policy must not silently widen access
            block("policy file unreadable -> fail-closed deny")
    return DEFAULT_ALLOW, DEFAULT_DENY


def block(reason: str):
    sys.stderr.write(json.dumps({"decision": "block", "reason": "auto-support: " + reason}) + "\n")
    sys.exit(2)


def allow():
    sys.exit(0)


def main():
    raw = sys.stdin.read()
    try:
        evt = json.loads(raw) if raw.strip() else {}
    except Exception:
        block("unparseable hook payload -> fail-closed deny")
    tool = evt.get("tool_name") or evt.get("tool") or ""
    ti = evt.get("tool_input") or evt.get("input") or {}
    if not str(tool).strip():
        block("missing/empty tool name -> fail-closed deny")
    allowlist, denylist = _load_policy()

    if tool in WRITE_TOOLS:
        block("write/edit tools are denied for a read-only support bot (%s)" % tool)
    if tool in NET_TOOLS:
        block("network tools are denied (no outbound exfiltration channel): %s" % tool)

    if tool in READ_TOOLS:
        path = ti.get("file_path") or ti.get("path") or ti.get("pattern") or ""
        if not path:
            block("read tool with no resolvable path -> fail-closed deny")
        v = G.path_verdict(str(path), allowlist, denylist)
        if not v.allowed:
            block("path outside knowledge boundary (%s): %s" % (v.reason, path))
        allow()

    if tool == "Bash":
        cmd = ti.get("command") or ""
        if _BASH_NET.search(cmd):
            block("bash network command denied (exfiltration risk): %s" % cmd[:80])
        if _BASH_WRITE.search(cmd):
            block("bash write/delete command denied (read-only bot): %s" % cmd[:80])
        # input redirection `< path` is a read channel -> path-check the target
        for m in _BASH_INREDIR.finditer(cmd):
            tgt = m.group(1)
            if not G.path_verdict(tgt, allowlist, denylist).allowed:
                block("bash input redirection reads outside the knowledge boundary: %s" % tgt)
        # interpreters / byte-tools can read arbitrary files via code or stdin -> fail-closed deny
        if _BASH_INTERP.search(cmd):
            block("bash interpreter/byte-tool denied (subprocess read bypass): %s" % cmd[:80])
        # ANY explicit path token outside the boundary is denied (covers cat/head AND ls secrets/)
        toks = re.findall(r"[\w./\\\-]+", cmd)
        for t in toks:
            if ("/" in t or "\\" in t or t.startswith(".")) and re.search(r"[./\\]", t):
                if not G.path_verdict(t, allowlist, denylist).allowed:
                    block("bash names a path outside the knowledge boundary: %s" % t)
        # default-DENY: only an explicit read util (cat/head/...) or an innocuous leading command
        # (echo/pwd/ls/...) reaches here cleanly; everything else is fail-closed denied. This closes
        # the previous fail-OPEN tail where an unmatched command was waved through.
        lead = re.split(r"[\s;|&]+", cmd.strip(), 1)[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        if _BASH_READ.search(cmd) or lead in _BASH_SAFE_LEAD:
            allow()
        block("non-allowlisted bash command -> fail-closed deny: %s" % cmd[:80])

    # mcp__discord__post_reply / relay tools etc. are allow-listed at the settings layer;
    # unknown tools here are denied (fail-closed) rather than waved through.
    if tool.startswith("mcp__"):
        # only the explicitly approved support/relay MCP verbs should reach here; anything
        # not pre-approved in settings.json never runs. Default-deny unknown mcp verbs.
        approved = set(filter(None, os.environ.get("AUTO_SUPPORT_MCP_ALLOW", "").split(",")))
        if tool in approved:
            allow()
        block("unapproved MCP tool -> fail-closed deny: %s" % tool)

    # DEFAULT-DENY unknown tools (fail-closed, per this file's contract). A file-reading or shell
    # tool registered under an UNRECOGNIZED name (e.g. "ReadFile", "Shell", a plugin tool) must NOT
    # slip through the old blanket allow() tail — that was a real bypass. Only an explicit allowlist
    # of genuinely low-risk built-ins passes; everything else is denied.
    SAFE_BUILTIN = {"TodoWrite", "TodoRead"}
    if tool in SAFE_BUILTIN:
        allow()
    block("unrecognized tool -> fail-closed deny (default-deny unknown tools): %s" % tool)


if __name__ == "__main__":
    main()
