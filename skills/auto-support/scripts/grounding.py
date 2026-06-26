#!/usr/bin/env python3
"""auto-support — grounding / faithfulness gate (have-evidence-or-abstain).

LLMs are confidently wrong, so we never trust model self-confidence. Two INDEPENDENT
dimensions decide whether a draft may proceed (architecture 3.1); either below threshold
downgrades the turn:

  retrieval_confidence  — did we actually find supporting public docs? (coverage of the query
                          terms by the retrieved allowlisted snippets)
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

_CITE_RE = re.compile(r"\[([^\]\s:]+(?:/[^\]\s:]+)*):(\d+)\]|\(([^\s)]+):(\d+)\)")
_SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")

# Salient numeric tokens (architecture §3.3 confidence calibration). Numbers ARE the high-stakes
# facts in support (rate limits, prices, versions, dates); a fabricated number ("100000" when the
# source says "100") is a confidently-wrong answer that the term-overlap faithfulness check misses.
# Only multi-digit numbers count as salient (single-digit step numbers / "v2" are ignored so they
# never cause an FP), and a grounded answer COPIES the number from the cited line, so its numbers
# are present in the cited snippet -> no FP on the normal grounded path.
_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")


def _salient_nums(text: str) -> set[str]:
    out = set()
    for m in _NUM_RE.finditer(text):
        d = re.sub(r"\D", "", m.group(0))
        if len(d) >= 2:
            out.add(d)
    return out


@dataclass
class Snippet:
    path: str
    line: int
    text: str


@dataclass
class GroundingResult:
    retrieval_confidence: float
    faithfulness: float
    band: str                       # "high" | "medium" | "low"
    grounded: bool
    ungrounded_sentences: list[str] = field(default_factory=list)
    cited_paths: list[str] = field(default_factory=list)


# Function words carry no grounding signal; coverage is measured over content terms only
# (mirrors retrieval.STOP) so "what is the rate limit?" scores on {rate, limit}, not {the, what}.
STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "do", "does", "did", "how", "what",
    "why", "when", "where", "which", "who", "you", "your", "yours", "i", "me", "my", "we",
    "our", "to", "of", "for", "and", "or", "in", "on", "with", "this", "that", "it", "its",
    "can", "could", "please", "tell", "give", "get", "about", "from", "into", "any",
}


def _terms(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2 and t not in STOP}


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
    for c in cites:
        path = c[0] or c[2]
        line = int(c[1] or c[3])
        snip = snippets_by_key.get((path, line))
        if snip:
            cited_nums |= _salient_nums(snip.text)
    for n in _salient_nums(decited):
        if n not in cited_nums:
            return False  # fabricated / uncited numeric value -> abstain (rather漏答 than错答)
    for c in cites:
        path = c[0] or c[2]
        line = int(c[1] or c[3])
        snip = snippets_by_key.get((path, line))
        if not snip:
            # citation points at something we did NOT retrieve from allowlist -> fabricated cite
            return False
        # require lexical overlap between the claim and the cited line
        overlap = sent_terms & _terms(snip.text)
        if not sent_terms or len(overlap) >= max(1, len(sent_terms) // 3):
            return True
    return False


def faithfulness(answer_text: str, snippets: list[Snippet]) -> tuple[float, list[str]]:
    by_key = {(s.path, s.line): s for s in snippets}
    sents = [s for s in _SENT_SPLIT.split(answer_text.strip()) if s.strip()]
    if not sents:
        return 0.0, []
    bad = [s for s in sents if not _sentence_supported(s, by_key)]
    return (len(sents) - len(bad)) / float(len(sents)), bad


def classify(query: str, answer_text: str, snippets: list[Snippet],
             retrieval_min: float = 0.7, faithfulness_min: float = 0.7,
             high_band: float = 0.9) -> GroundingResult:
    rc = retrieval_confidence(query, snippets)
    ff, bad = faithfulness(answer_text, snippets)
    cited = sorted({s.path for s in snippets})
    if rc >= high_band and ff >= high_band:
        band = "high"
    elif rc >= retrieval_min and ff >= faithfulness_min:
        band = "medium"
    else:
        band = "low"
    grounded = band in ("high", "medium")
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
