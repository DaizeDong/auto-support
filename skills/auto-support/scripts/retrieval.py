#!/usr/bin/env python3
"""auto-support — allowlist-gated project retrieval (knowledge boundary at the file layer).

The knowledge boundary is enforced by what can PHYSICALLY enter context, not by asking the
model to be careful. This walks the product root, admits only allowlisted / non-denylisted
files (guardrails.path_verdict), and — belt and suspenders — scans every snippet for secrets
before returning it. A snippet that trips the secret scanner is dropped (fail-closed), so even
a misfiled credential in an "allowed" doc never reaches the answer context.

Parsing and source binding use stdlib. Splitting large plain-prose chapters additionally
requires a bound interpretation through installed llmcall. The same allowlist/denylist
drives the PreToolUse hook so a subprocess cannot bypass the file boundary.
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
import policy as P  # noqa: E402
import document_boundary as D  # noqa: E402
from query_terms import content_terms  # noqa: E402
from source_scope import build_scope  # noqa: E402
from semantic_scope import interpret_scope  # noqa: E402


@dataclass
class Snippet:
    path: str            # relative, allowlisted
    line: int
    text: str            # exact complete source span, including whitespace
    required_citations: tuple[str, ...] = ()


class SearchResults(list):
    """Bounded complete units, with explicit disclosure when matching units were omitted."""
    def __init__(self, snippets=(), *, complete=True, scope_graphs=None):
        super().__init__(snippets)
        self.complete = complete
        self.scope_graphs = scope_graphs or {}


class InstructionUnits(list):
    def __init__(self, units=(), *, scope=None, complete=True):
        super().__init__(units)
        self.scope = scope
        self.complete = complete


_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+\S")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_PEER_CONTEXT_CHARS = 4000
_BLOCK_START = re.compile(
    r"^(?:#{1,6}(?:[ \t]|$)|>|(?:[-+*]|\d+[.)])(?:[ \t]|$)|(?:=+|-+)[ \t]*$)")
_INLINE_MARKUP = re.compile(r"[`\\*_\[\]~<|]")
_ORDERED_TITLE = re.compile(r"^\d+[.)](?:[ \t]|$)")
_HTML_BLOCK_START = re.compile(r"^ {0,3}<[A-Za-z!/?]")
def _has_markdown_structure(lines):
    """Conservatively distinguish plain prose from Markdown blocks and inline markup.

    Four-column tab expansion is only a classification view; original source spans
    are never rewritten. Any nonempty indented line keeps its entire section attached,
    including unmarked continuations. Quotes allow no space after their marker, and
    empty list items still introduce structure. Uncertain markup stays in context.
    """
    first = True
    for raw in lines:
        line = raw.rstrip("\r\n").expandtabs(4)
        text = line.lstrip(" ")
        if not text:
            continue
        heading = _HEADING.match(line)
        if first and heading:
            title = line[heading.end(1):].lstrip(" ")
            first = False
            if _ORDERED_TITLE.match(title) or _INLINE_MARKUP.search(title):
                return True
            continue
        first = False
        if len(line) - len(text) >= 4:
            return True
        if _BLOCK_START.match(text) or _INLINE_MARKUP.search(text):
            return True
    return False


def _instruction_units(lines):
    """Keep section subtrees and neighboring procedural context together.

    Consecutive bounded peer sections form one unit regardless of language or query
    overlap. Numbered steps, code, lists and quotations remain attached even when
    oversized, so the budget rejects the whole procedure instead of losing a step.
    Large plain-prose peers are provisional boundaries. Splitting them requires an
    exhaustive source-bound semantic interpretation; lexical absence is not evidence
    that a peer is independent.
    """
    headings = []
    fence = None
    comment = False
    html_block = False
    for index, line in enumerate(lines):
        marker = _FENCE.match(line)
        if fence:
            if (marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence)
                    and not marker[2].strip()):
                fence = None
            continue
        if _HTML_BLOCK_START.match(line):
            html_block = True
        if comment or "<!--" in line:
            comment = "-->" not in line
            continue
        if marker:
            fence = marker[1]
            continue
        heading = _HEADING.match(line)
        if heading:
            headings.append((index, len(heading[1])))
    if fence or comment:
        # An unfinished construct has no trustworthy boundary.
        return InstructionUnits(complete=False)
    if html_block:
        # Markdown-looking lines inside raw HTML are not reliable section boundaries.
        # Retain the whole file rather than infer a partial HTML/Markdown parse.
        return InstructionUnits([[(0, len(lines))]])
    levels = [level for _, level in headings]
    if levels and levels[0] == 1 and levels.count(1) == 1:
        levels = levels[1:]
    if not levels:
        if not lines:
            return InstructionUnits()
        graph = build_scope(lines, [(0, len(lines))], headings, [(0, len(lines))])
        return InstructionUnits([[(0, len(lines))]], scope=graph,
                                complete=not graph.unresolved_references)
    level = min(levels)
    starts = [index for index, depth in headings if depth == level]
    if len(starts) < 2:
        graph = build_scope(lines, [(0, len(lines))], headings, [(0, len(lines))])
        return InstructionUnits([[(0, len(lines))]], scope=graph,
                                complete=not graph.unresolved_references)
    spans = list(zip(starts, starts[1:] + [len(lines)]))
    preamble = []
    if starts[0] and any(line.strip() for line in lines[:starts[0]]):
        preamble.append((0, starts[0]))
    provisional = {
        index for index, (begin, end) in enumerate(spans)
        if sum(map(len, lines[begin:end])) > _PEER_CONTEXT_CHARS
        and not _has_markdown_structure(lines[begin:end])
    }
    groups = []
    pending = None
    for index, (begin, end) in enumerate(spans):
        separate_chapter = index in provisional
        if separate_chapter:
            if pending is not None:
                groups.append(pending)
                pending = None
            groups.append((begin, end))
        else:
            pending = (pending[0] if pending is not None else begin, end)
    if pending is not None:
        groups.append(pending)
    graph = build_scope(lines, spans, headings, groups)
    if graph.unresolved_references:
        return InstructionUnits(scope=graph, complete=False)
    if len(groups) > 1:
        interpreted = interpret_scope(graph, lines)
        if interpreted is None:
            return InstructionUnits(scope=graph, complete=False)
        graph = interpreted
    units = []
    for group in groups:
        seeds = {index for index, (begin, end) in enumerate(spans)
                 if group[0] <= begin and end <= group[1]}
        required = graph.required_sections(seeds)
        others = [other for other in groups if other != group and any(
            index in required and other[0] <= begin and end <= other[1]
            for index, (begin, end) in enumerate(spans))]
        units.append([group] + others + (preamble if -1 in required else []))
    return InstructionUnits(units, scope=graph, complete=not graph.unresolved_references)




def _content_terms(text: str) -> list[str]:
    return sorted(content_terms(text))


def _iter_files(root: str):
    def failed_scan(error):
        raise error

    for dirpath, dirnames, filenames in os.walk(root, onerror=failed_scan):
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
        resolved = os.path.realpath(full)
        resolved_rel = os.path.relpath(resolved, os.path.realpath(root)).replace("\\", "/")
        if (G.path_verdict(rel, allowlist, denylist).allowed
                and G.path_verdict(resolved_rel, allowlist, denylist).allowed
                and D.allowed_document(full)):
            out.append(rel)
    return sorted(out)


def search(root: str, query: str, allowlist: Iterable[str], denylist: Iterable[str],
           max_snippets: int = 5, max_chars: int = 4000) -> list[Snippet]:
    """Retrieve whole source units and their mandatory context within one total budget.

    Unsafe units are excluded as a whole. A capped result is marked incomplete so the
    draft pipeline cannot mistake an omitted instruction for fully grounded evidence.
    """
    root = os.path.abspath(root)
    terms = set(_content_terms(query))
    if not terms or max_snippets <= 0 or max_chars <= 0:
        return SearchResults()
    scored = []
    complete = True
    scope_graphs = {}
    try:
        documents = allowed_files(root, allowlist, denylist)
    except OSError:
        print("[retrieval] incomplete evidence: the public document inventory could not be read", file=sys.stderr)
        return SearchResults(complete=False)
    for rel in documents:
        try:
            resolved_rel = os.path.relpath(os.path.realpath(os.path.join(root, rel)), os.path.realpath(root)).replace("\\", "/")
            path = os.path.join(root, rel)
            if (not G.path_verdict(resolved_rel, allowlist, denylist).allowed
                    or not D.allowed_document(path)):
                complete = False
                continue
            with open(path, "r", encoding="utf-8", newline="") as f:
                if not D.single_link_regular(os.fstat(f.fileno())):
                    complete = False
                    continue
                lines = f.readlines()
                if not D.single_link_regular(os.fstat(f.fileno())):
                    complete = False
                    continue
        except (UnicodeError, OSError):
            # An admitted but unavailable document may contain required context.
            complete = False
            continue
        units = _instruction_units(lines)
        if units.scope is not None:
            scope_graphs[rel] = units.scope
        if not units.complete:
            if terms & set(_content_terms(''.join(lines))):
                complete = False
            continue
        for spans in units:
            start, end = spans[0]
            score = len(terms & set(_content_terms("".join(lines[start:end]))))
            if score == 0:
                continue
            snippets = [Snippet(rel, begin + 1, "".join(lines[begin:finish]))
                        for begin, finish in sorted(spans)]
            if any(G.scan_secrets(s.text).hit or G.detect_injection(s.text).suspicious
                   for s in snippets):
                complete = False
                continue
            required = tuple("%s:%d" % (s.path, s.line) for s in snippets)
            for snippet in snippets:
                snippet.required_citations = required
            scored.append((-score, rel, start, snippets))
    scored.sort(key=lambda item: item[:3])
    hits = {}
    budget = max_chars
    for _, rel, _, snippets in scored:
        additions = [s for s in snippets if (s.path, s.line) not in hits]
        size = sum(len(s.text) for s in additions)
        if len(hits) + len(additions) > max_snippets or size > budget:
            complete = False
            continue
        budget -= size
        for snippet in snippets:
            key = (snippet.path, snippet.line)
            if key in hits:
                snippet.required_citations = tuple(sorted(
                    set(snippet.required_citations) | set(hits[key].required_citations)))
            hits[key] = snippet
    if not complete:
        print("[retrieval] incomplete evidence: a public document was unavailable, "
              "or matching context was unsafe or exceeded the total retrieval budget", file=sys.stderr)
    return SearchResults([hits[key] for key in sorted(hits)], complete=complete,
                         scope_graphs=scope_graphs)


def main():
    ap = argparse.ArgumentParser(description="allowlist-gated retrieval over a product root")
    ap.add_argument("--root", required=True)
    ap.add_argument("--policy", help="path to policy.json (index_allowlist/secret_denylist)")
    ap.add_argument("--demo", action="store_true", help="explicitly use built-in demonstration defaults")
    ap.add_argument("--query", default="")
    ap.add_argument("--list-files", action="store_true")
    a = ap.parse_args()

    allow = ["README*", "docs/**", "public-faq/**", "CHANGELOG*", "examples/**", "**/*.example"]
    deny = ["**/.env", "**/.env.*", "*.pem", "*.key", "id_rsa", "secrets/**", "credentials/**",
            "vault/**", "src/**", "internal/**", "proprietary/**", "algorithms/**",
            "**/customer_data/**", "**/*.pii.*"]
    selected = a.policy or os.environ.get("AUTO_SUPPORT_POLICY")
    if a.demo and selected:
        ap.error("--demo cannot override an explicit policy")
    try:
        if selected:
            pol = P.load_policy(selected)
            if os.path.realpath(a.root) != str(P.resolve_product_root(selected, pol)):
                raise P.PolicyError("--root must match the selected product")
            allow, deny = pol["index_allowlist"], pol["secret_denylist"]
        elif not a.demo:
            ap.error("select --policy or explicitly use --demo")
    except P.PolicyError as exc:
        ap.error(str(exc))

    if a.list_files:
        try:
            documents = allowed_files(a.root, allow, deny)
        except OSError:
            print("[retrieval] incomplete evidence: the public document inventory could not be read", file=sys.stderr)
            return 2
        print(json.dumps(documents, indent=2))
        return 0
    snips = search(a.root, a.query, allow, deny)
    print(json.dumps({"complete": snips.complete,
                      "snippets": [asdict(s) for s in snips] if snips.complete else []},
                     indent=2, ensure_ascii=False))
    return 0 if snips.complete else 2


if __name__ == "__main__":
    sys.exit(main())
