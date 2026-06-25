#!/usr/bin/env python3
"""auto-support — allowlist-gated project retrieval (knowledge boundary at the file layer).

The knowledge boundary is enforced by what can PHYSICALLY enter context, not by asking the
model to be careful. This walks the product root, admits only allowlisted / non-denylisted
files (guardrails.path_verdict), and — belt and suspenders — scans every snippet for secrets
before returning it. A snippet that trips the secret scanner is dropped (fail-closed), so even
a misfiled credential in an "allowed" doc never reaches the answer context.

Pure stdlib. No vector store (precise Read/Grep grounding per the architecture); the same
allowlist/denylist drives the PreToolUse hook so a subprocess cannot bypass this path.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Iterable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrails as G  # noqa: E402


@dataclass
class Snippet:
    path: str            # relative, allowlisted
    line: int
    text: str            # the matching line (secret-scanned, safe to ground on)


# Function words carry no retrieval signal and (e.g. "the") would match every line; drop them
# so ranking reflects topical terms. Shared spelling with grounding.STOP for consistent scoring.
STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "do", "does", "did", "how", "what",
    "why", "when", "where", "which", "who", "you", "your", "yours", "i", "me", "my", "we",
    "our", "to", "of", "for", "and", "or", "in", "on", "with", "this", "that", "it", "its",
    "can", "could", "please", "tell", "give", "get", "about", "from", "into", "any",
}


def _content_terms(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) > 2 and t not in STOP]


def _iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        # prune obviously-secret dirs early (perf + defense): never descend into them
        dirnames[:] = [d for d in dirnames if d.lower() not in {
            ".git", "node_modules", "__pycache__", "secrets", "credentials", "vault", ".venv"
        }]
        for fn in filenames:
            yield os.path.join(dirpath, fn)


def allowed_files(root: str, allowlist: Iterable[str], denylist: Iterable[str]) -> list[str]:
    root = os.path.abspath(root)
    out = []
    for full in _iter_files(root):
        rel = os.path.relpath(full, root).replace("\\", "/")
        if G.path_verdict(rel, allowlist, denylist).allowed:
            out.append(rel)
    return sorted(out)


def search(root: str, query: str, allowlist: Iterable[str], denylist: Iterable[str],
           max_snippets: int = 5, max_chars: int = 4000) -> list[Snippet]:
    """Grep `query` (case-insensitive whole-word-ish) over allowlisted files only.

    Every returned line is secret-scanned; lines that trip the scanner are dropped. Caps at
    max_snippets / max_chars to prevent context flooding (architecture: 3-5 snippets)."""
    root = os.path.abspath(root)
    terms = set(_content_terms(query))
    if not terms:
        return []
    scored: list[tuple[int, str, int, str]] = []  # (-score, path, line, text) for ranking
    for rel in allowed_files(root, allowlist, denylist):
        try:
            with open(os.path.join(root, rel), "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            continue
        for i, line in enumerate(lines, 1):
            line_terms = set(_content_terms(line))
            score = len(terms & line_terms)
            if score == 0:
                continue
            if G.scan_secrets(line).hit:        # fail-closed: never ground on a secret-bearing line
                continue
            if G.detect_injection(line).suspicious:  # indirect injection hiding in a doc -> skip
                continue
            scored.append((-score, rel, i, line.strip()[:400]))
    # rank by relevance (most query terms matched first), then path/line for determinism
    scored.sort()
    hits: list[Snippet] = []
    budget = max_chars
    for negscore, rel, i, txt in scored:
        if len(txt) > budget:
            continue
        budget -= len(txt)
        hits.append(Snippet(rel, i, txt))
        if len(hits) >= max_snippets or budget <= 0:
            break
    return hits


def main():
    ap = argparse.ArgumentParser(description="allowlist-gated retrieval over a product root")
    ap.add_argument("--root", required=True)
    ap.add_argument("--policy", help="path to policy.json (index_allowlist/secret_denylist)")
    ap.add_argument("--query", default="")
    ap.add_argument("--list-files", action="store_true")
    a = ap.parse_args()

    allow = ["README*", "docs/**", "public-faq/**", "CHANGELOG*", "examples/**", "**/*.example"]
    deny = ["**/.env", "**/.env.*", "*.pem", "*.key", "id_rsa", "secrets/**", "credentials/**",
            "vault/**", "src/**", "internal/**", "proprietary/**", "algorithms/**",
            "**/customer_data/**", "**/*.pii.*"]
    if a.policy and os.path.isfile(a.policy):
        pol = json.load(open(a.policy, encoding="utf-8"))
        allow = pol.get("index_allowlist", allow)
        deny = pol.get("secret_denylist", deny)

    if a.list_files:
        print(json.dumps(allowed_files(a.root, allow, deny), indent=2))
        return 0
    snips = search(a.root, a.query, allow, deny)
    print(json.dumps([asdict(s) for s in snips], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
