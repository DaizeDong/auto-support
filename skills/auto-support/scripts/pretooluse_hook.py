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
import shlex
import sys
import ntpath
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrails as G  # noqa: E402
import policy as P  # noqa: E402
import document_boundary as D  # noqa: E402

DEFAULT_ALLOW = ["README*", "docs/**", "public-faq/**", "CHANGELOG*", "examples/**", "**/*.example"]
DEFAULT_DENY = ["**/.env", "**/.env.*", "*.pem", "*.key", "id_rsa", "secrets/**", "credentials/**",
                "vault/**", "src/**", "internal/**", "proprietary/**", "algorithms/**",
                "**/customer_data/**", "**/*.pii.*", "**/CLAUDE.md", "**/.git/**"]

# Tools that read files -> path-check against the knowledge boundary.
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead"}
# Tools that mutate or exfiltrate -> always denied for a read-only support bot.
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Update"}
NET_TOOLS = {"WebFetch", "WebSearch"}


def _load_policy():
    p = os.environ.get("AUTO_SUPPORT_POLICY")
    if p:
        try:
            pol = P.load_policy(p)
            return pol["index_allowlist"], pol["secret_denylist"], P.resolve_product_root(p, pol)
        except P.PolicyError:
            # fail-closed: an unreadable policy must not silently widen access
            block("policy file unreadable -> fail-closed deny")
    return DEFAULT_ALLOW, DEFAULT_DENY, Path.cwd().resolve()


def _bounded_path(raw, root, cwd, allowlist, denylist, *, directory=False):
    if (not isinstance(raw, str) or not raw or "\x00" in raw or "~" in raw
            or G._has_traversal(raw) or any(c in raw for c in "*?[]")):
        return False
    path = Path(raw)
    if (ntpath.splitdrive(raw)[0] or ntpath.isabs(raw)) and not path.is_absolute():
        return False
    requested = path if path.is_absolute() else cwd / path
    try:
        relative = requested.relative_to(root).as_posix()
        resolved = requested.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return False
    if directory:
        relative = relative.rstrip("/") + "/__directory__.md"
        resolved = resolved.rstrip("/") + "/__directory__.md"
    return (G.path_verdict(relative, allowlist, denylist).allowed
            and G.path_verdict(resolved, allowlist, denylist).allowed
            and D.allowed_document(requested, missing_ok=True, directory=directory))


def _search_target(raw, root, cwd, allowlist, denylist):
    """Directory content searches are allowed only when every file is in scope."""
    if not isinstance(raw, str) or not raw:
        return False
    path = Path(raw)
    path = path if path.is_absolute() else cwd / path
    if not _bounded_path(raw, root, cwd, allowlist, denylist, directory=path.is_dir()):
        return False
    if path.is_dir():
        for item in path.rglob("*"):
            if item.is_file() and not _bounded_path(str(item), root, cwd, allowlist, denylist):
                return False
            if item.is_symlink() and item.is_dir():
                return False
    return True


def _safe_shell_read(command, allowlist, denylist, root, cwd):
    """Recognize a small literal grammar; never try to parse general shell code."""
    if not isinstance(command, str) or re.search(r"[\r\n;&|<>$`\\*?{}()\[\]~]", command):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if not words:
        return False
    verb, args = words[0], words[1:]
    if verb in {"pwd", "true", "false"}:
        return not args
    if verb == "echo":
        return all(not arg.startswith("-") for arg in args)
    if verb not in {"cat", "head", "tail", "ls"} or not args:
        return False
    for path in args:
        if path.startswith("-"):
            return False
        if not _bounded_path(path, root, cwd, allowlist, denylist, directory=verb == "ls"):
            return False
    return True


def block(reason: str):
    sys.stderr.write(json.dumps({"decision": "block", "reason": "auto-support: " + reason}) + "\n")
    sys.exit(2)


def allow():
    sys.exit(0)


def main():
    raw = sys.stdin.buffer.read().decode("utf-8-sig", "replace")
    try:
        evt = json.loads(raw) if raw.strip() else {}
    except Exception:
        block("unparseable hook payload -> fail-closed deny")
    if not isinstance(evt, dict):
        block("hook payload must be an object")
    tool = evt.get("tool_name") or evt.get("tool") or ""
    ti = evt.get("tool_input") or evt.get("input") or {}
    if not isinstance(ti, dict) or not isinstance(tool, str):
        block("tool name and input types are invalid")
    if not str(tool).strip():
        block("missing/empty tool name -> fail-closed deny")
    allowlist, denylist, root = _load_policy()
    raw_cwd = evt.get("cwd", os.getcwd())
    if not isinstance(raw_cwd, str) or not Path(raw_cwd).is_absolute():
        block("hook cwd must be an absolute directory")
    cwd = Path(raw_cwd).resolve()

    if tool in WRITE_TOOLS:
        block("write/edit tools are denied for a read-only support bot (%s)" % tool)
    if tool in NET_TOOLS:
        block("network tools are denied (no outbound exfiltration channel): %s" % tool)

    if tool in READ_TOOLS:
        if tool == "Glob":
            raw_path, pattern = ti.get("path"), ti.get("pattern")
            if (not isinstance(pattern, str) or not pattern or G._has_traversal(pattern)
                    or ntpath.isabs(pattern) or ":" in pattern or "~" in pattern
                    or not _search_target(raw_path, root, cwd, allowlist, denylist)):
                block("Glob requires an explicit bounded search root and relative pattern")
        elif tool == "Grep":
            if not _search_target(ti.get("path"), root, cwd, allowlist, denylist):
                block("Grep requires an explicit target whose searched files are all public")
        else:
            path = ti.get("file_path") or ti.get("notebook_path") or ti.get("path")
            if not _bounded_path(path, root, cwd, allowlist, denylist):
                block("read target is outside the selected public boundary")
        allow()

    if tool == "Bash":
        cmd = ti.get("command") or ""
        if not _safe_shell_read(cmd, allowlist, denylist, root, cwd):
            block("shell command is outside the literal read-only grammar")
        allow()

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
    # slip through the old blanket allow() tail, that was a real bypass. Only an explicit allowlist
    # of genuinely low-risk built-ins passes; everything else is denied.
    SAFE_BUILTIN = {"TodoWrite", "TodoRead"}
    if tool in SAFE_BUILTIN:
        allow()
    block("unrecognized tool -> fail-closed deny (default-deny unknown tools): %s" % tool)


if __name__ == "__main__":
    main()
