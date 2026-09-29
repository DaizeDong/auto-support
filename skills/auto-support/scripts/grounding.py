#!/usr/bin/env python3
"""auto-support — grounding / faithfulness gate (have-evidence-or-abstain).

LLMs are confidently wrong, so we never trust model self-confidence. Two INDEPENDENT
dimensions decide whether a draft may proceed (architecture 3.1); either below threshold
downgrades the turn:

  retrieval_confidence  — did we actually find supporting public docs? (coverage of the query
                          terms by the emitted, cited allowlisted snippets)
  faithfulness          — is every claim in the answer traceable to a retrieved snippet?
                          (deterministic floor here = citation present + lexical support of the
                          cited line; the full check is an INDEPENDENT judge LLM, interface in
                          `judge_faithfulness` — kept separate from the answering chain so it
                          cannot self-endorse a hallucination.)

This module's deterministic gate is the fail-closed floor that runs with zero LLM and zero
network, so the security path is testable in CI. If the floor says "ungrounded", we abstain
regardless of what any model claims.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from query_terms import content_terms

_CITE_RE = re.compile(r"\[([^\]\r\n\t:]+):([1-9][0-9]*)\]|\(([^)\r\n\t:]+):([1-9][0-9]*)\)")
_SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")

# Preserve decimal points and all digits: 2.5, 25 and 2 are different claims.
_NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")


def _salient_nums(text: str) -> set[str]:
    # Explicit ordered instruction labels are presentation, not product facts.
    text = re.sub(r"\bstep\s+\d+\s*:", "", text, flags=re.I)
    return {m.group(0).replace(",", "") for m in _NUM_RE.finditer(text)}


@dataclass
class Snippet:
    path: str
    line: int
    text: str
    required_citations: tuple[str, ...] = ()


@dataclass
class GroundingResult:
    retrieval_confidence: float
    faithfulness: float
    band: str                       # "high" | "medium" | "low"
    grounded: bool
    ungrounded_sentences: list[str] = field(default_factory=list)
    cited_paths: list[str] = field(default_factory=list)




def _terms(text: str) -> set[str]:
    return content_terms(text)


def retrieval_confidence(query: str, snippets: list[Snippet]) -> float:
    q = _terms(query)
    if not q:
        return 0.0
    covered = set()
    for s in snippets:
        covered |= (q & _terms(s.text))
    return len(covered) / float(len(q))


def _sentence_supported(sentence: str, snippets_by_key: dict[tuple[str, int], Snippet]) -> bool:
    cites = _CITE_RE.findall(sentence)
    if not cites:
        return False  # no citation -> not grounded (architecture: every claim must cite)
    decited = re.sub(_CITE_RE, "", sentence)
    sent_terms = _terms(decited)
    # §3.3 numeric calibration: a SALIENT number in the claim that appears in NONE of the cited
    # snippets is a fabricated fact (confidently-wrong) -> not supported, even if the words overlap.
    cited_nums: set[str] = set()
    cited_snippets = []
    for c in cites:
        path = c[0] or c[2]
        line = int(c[1] or c[3])
        snip = snippets_by_key.get((path, line))
        if snip is None:
            return False
        cited_snippets.append(snip)
        cited_nums |= _salient_nums(snip.text)
    for n in _salient_nums(decited):
        if n not in cited_nums:
            return False  # fabricated / uncited numeric value -> abstain (rather漏答 than错答)
    for snip in cited_snippets:
        # require lexical overlap between the claim and the cited line
        overlap = sent_terms & _terms(snip.text)
        if not sent_terms or len(overlap) >= max(1, len(sent_terms) // 3):
            return True
    return False


def faithfulness(answer_text: str, snippets: list[Snippet]) -> tuple[float, list[str]]:
    if literal_citations(answer_text, snippets) is not None:
        return 1.0, []
    if any(s.required_citations for s in snippets):
        return 0.0, [answer_text]
    by_key = {(s.path, s.line): s for s in snippets}
    sents = []
    literal = set()
    for line in answer_text.strip().splitlines():
        line = line.strip()
        # A complete literal excerpt binds all its punctuation to its trailing citation.
        # Arbitrary generated text still uses the claim checks below.
        matched = False
        for snip in snippets:
            expected = "%s [%s:%d]" % (snip.text.strip(), snip.path, snip.line)
            if line == expected:
                matched = True
                literal.add(line)
                break
        if matched:
            sents.append(line)
        else:
            sents.extend(s for s in _SENT_SPLIT.split(line) if s.strip())
    if not sents:
        return 0.0, []
    bad = [s for s in sents if s not in literal and not _sentence_supported(s, by_key)]
    return (len(sents) - len(bad)) / float(len(sents)), bad


def render_excerpt(snippet: Snippet) -> str:
    """Preserve source whitespace and executable tokens before appending a citation."""
    return "%s [%s:%d]" % (snippet.text, snippet.path, snippet.line)


def literal_citations(answer_text: str, snippets: list[Snippet]) -> set[str] | None:
    """Bind complete emitted spans, including all required context, to exact source bytes.

    Lexical support alone cannot establish units, negation or additional facts.
    The executable draft pipeline therefore accepts this narrower proof only.
    """
    if not answer_text:
        return None
    excerpts = sorted(((render_excerpt(s), s) for s in snippets), key=lambda item: -len(item[0]))
    remaining = answer_text
    cited = set()
    required = set()
    last_line = {}
    while remaining:
        for excerpt, snippet in excerpts:
            if remaining == excerpt or remaining.startswith(excerpt + "\n"):
                if snippet.line <= last_line.get(snippet.path, 0):
                    return None
                last_line[snippet.path] = snippet.line
                cited.add("%s:%d" % (snippet.path, snippet.line))
                required.update(snippet.required_citations)
                remaining = remaining[len(excerpt):]
                if remaining:
                    remaining = remaining[1:]
                break
        else:
            return None
    return cited if required <= cited else None


def classify(query: str, answer_text: str, snippets: list[Snippet],
             retrieval_min: float = 0.7, faithfulness_min: float = 0.7,
             high_band: float = 0.9) -> GroundingResult:
    used = literal_citations(answer_text, snippets)
    if used is None:
        # Standalone lexical callers still use cited evidence only. The draft
        # pipeline requires a complete literal proof before reaching this gate.
        used = {"%s:%s" % (a or c, b or d) for a, b, c, d in _CITE_RE.findall(answer_text)}
    emitted = [s for s in snippets if "%s:%d" % (s.path, s.line) in used]
    rc = retrieval_confidence(query, emitted)
    ff, bad = faithfulness(answer_text, snippets)
    cited = sorted({s.path for s in emitted})
    if rc >= high_band and ff >= high_band:
        band = "high"
    elif rc >= retrieval_min and ff >= faithfulness_min:
        band = "medium"
    else:
        band = "low"
    grounded = bool(answer_text.strip()) and not bad and band in ("high", "medium")
    return GroundingResult(round(rc, 3), round(ff, 3), band, grounded, bad, cited)


def judge_faithfulness(query, answer_text, snippets, llm_call):
    """Full faithfulness via an INDEPENDENT judge LLM (architecture 3.3).

    `llm_call(prompt) -> float in [0,1]` is injected so the judge is a fresh context (temp 0,
    no shared history). DEFERRED until a live LLM is wired; the deterministic `classify` floor
    runs unconditionally so abstention is never blocked on this. Spotlight the snippets before
    judging (they are untrusted)."""
    raise NotImplementedError(
        "judge_faithfulness is the LLM tier; wire llm_call at integration. classify() is the gate floor."
    )
