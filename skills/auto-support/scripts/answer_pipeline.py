#!/usr/bin/env python3
"""auto-support — the four-gate pipeline for ONE Discord message (defense in depth, fail-closed).

    entry gate   -> intent + injection classification (spotlighted)        [Layer 0/1]
    retrieval    -> allowlist-only search, secret-scrubbed snippets         [Layer 2]
    generation   -> grounded-only (pluggable LLM; deterministic default)    [Layer 3]
    grounding    -> retrieval_conf x faithfulness, have-evidence-or-abstain  [Layer 3]
    egress       -> structured schema + DLP + citation integrity            [Layer 4]

Every gate is fail-closed: the only outcomes are a *draft* (which in MVP goes to a founder
review channel, never straight to the user), or one of {cancelled, abstain, escalate,
blocked-leak} — and the user only ever sees a grounded answer or one neutral refusal line.

`generate` is injected so a real LLM can replace the deterministic extractor without touching
the security gates. The default extractor returns ONLY retrieved public snippets with
citations, so the whole pipeline runs in CI with no LLM and no network — which is exactly how
the red-team suite exercises it.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrails as G            # noqa: E402
import retrieval as R            # noqa: E402
import grounding as GR           # noqa: E402
import egress_dlp as E           # noqa: E402

INTENTS = ("product_usage_question", "chitchat", "off_topic", "sensitive_or_injection", "unclear")
_CHITCHAT = ("hi", "hello", "hey", "thanks", "thank you", "lol", "gm", "good morning", "ty")
_PRODUCT_HINTS = ("how", "where", "what", "why", "can i", "does", "setup", "install", "config",
                  "error", "use", "api", "rate limit", "pricing", "docs", "feature", "support")


@dataclass
class Decision:
    decision: str                # answered | abstain | escalate | blocked-leak | cancelled
    intent: str
    trigger: str = ""
    response_text: str = ""      # grounded draft, OR neutral refusal — user-safe either way
    retrieval_confidence: float = 0.0
    faithfulness: float = 0.0
    citations: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)   # internal diagnostics, never user-facing


def classify_intent(query: str) -> str:
    q = (query or "").strip().lower()
    if not q:
        return "unclear"
    if G.detect_injection(query).suspicious:
        return "sensitive_or_injection"
    if any(q == c or q.startswith(c + " ") or q.startswith(c + "!") for c in _CHITCHAT) and len(q) < 30:
        return "chitchat"
    if any(h in q for h in _PRODUCT_HINTS) or q.endswith("?"):
        return "product_usage_question"
    return "unclear"


def _default_generate(query: str, snippets: list[GR.Snippet]) -> dict:
    """Deterministic grounded extractor: emit ONLY retrieved public lines, each with its
    citation embedded so the grounding gate can verify it. Never invents text.

    Internal terminal punctuation (. ? !) is neutralised so the citation cannot be split off
    its claim by the sentence splitter -> one snippet stays one grounded sentence."""
    import re as _re
    sents, cites = [], []
    for s in snippets:
        clean = _re.sub(r"[.!?]+", " ", s.text).strip().rstrip(" ,")
        if not clean:
            continue
        sents.append("%s [%s:%d]." % (clean, s.path, s.line))
        cites.append("%s:%d" % (s.path, s.line))
    return {
        "response_text": " ".join(sents),
        "needs_escalation": False,
        "cited_sources": cites,
        "cited_internal_paths": [],     # canary — stays empty
        "contains_secret": False,       # canary — stays false
    }


def handle(query: str, root: str, allowlist, denylist, *,
           generate: Callable[[str, list], dict] | None = None,
           retrieval_min: float = 0.7, faithfulness_min: float = 0.7,
           high_band: float = 0.9) -> Decision:
    generate = generate or _default_generate

    # ---- Gate 0/1: entry (intent + injection). Untrusted input is treated as data. ----
    intent = classify_intent(query)
    if intent == "sensitive_or_injection":
        return Decision("escalate", intent, trigger="injection",
                        response_text=E.NEUTRAL_REFUSAL, reasons=["entry:injection"])
    if intent in ("chitchat", "off_topic"):
        return Decision("cancelled", intent, trigger="off_topic", response_text="")
    if intent == "unclear":
        return Decision("escalate", intent, trigger="unclear",
                        response_text=E.NEUTRAL_REFUSAL, reasons=["entry:unclear"])

    # ---- Gate 2: retrieval (allowlist only; snippets already secret-scrubbed) ----
    raw = R.search(root, query, allowlist, denylist)
    snippets = [GR.Snippet(s.path, s.line, s.text) for s in raw]
    if not snippets:
        return Decision("escalate", intent, trigger="no_evidence",
                        response_text=E.NEUTRAL_REFUSAL, reasons=["retrieval:empty"])

    # ---- Gate 3a: generation (grounded-only) ----
    answer = generate(query, snippets)

    # ---- Gate 3b: grounding (have-evidence-or-abstain) ----
    g = GR.classify(query, answer.get("response_text", ""), snippets,
                    retrieval_min, faithfulness_min, high_band)
    if not g.grounded:
        return Decision("escalate", intent, trigger="low_confidence",
                        response_text=E.NEUTRAL_REFUSAL,
                        retrieval_confidence=g.retrieval_confidence, faithfulness=g.faithfulness,
                        reasons=["grounding:low band=%s" % g.band])

    # ---- Gate 4: egress (schema + DLP + citation integrity) ----
    eg = E.evaluate(answer, allowlist=allowlist, denylist=denylist)
    if not eg.allowed:
        leak = any(r.startswith(("secret:", "pii:", "canary:")) or r in ("markdown-exfil-channel",)
                   for r in eg.reasons)
        return Decision("blocked-leak" if leak else "escalate", intent,
                        trigger="suspected_leak" if leak else "egress_block",
                        response_text=E.NEUTRAL_REFUSAL,
                        retrieval_confidence=g.retrieval_confidence, faithfulness=g.faithfulness,
                        reasons=["egress:" + r for r in eg.reasons])

    # passed all four gates -> DRAFT (MVP: goes to founder review, not auto-sent)
    return Decision("answered", intent, trigger="",
                    response_text=eg.response_text,
                    retrieval_confidence=g.retrieval_confidence, faithfulness=g.faithfulness,
                    citations=g.cited_paths)


def main():
    import argparse, json
    ap = argparse.ArgumentParser(description="run the auto-support four-gate pipeline on one message")
    ap.add_argument("--root", required=True)
    ap.add_argument("--query", required=True)
    ap.add_argument("--policy")
    a = ap.parse_args()
    allow = ["README*", "docs/**", "public-faq/**", "CHANGELOG*", "examples/**", "**/*.example"]
    deny = ["**/.env", "**/.env.*", "*.pem", "*.key", "secrets/**", "src/**", "internal/**",
            "algorithms/**", "proprietary/**", "**/customer_data/**", "**/*.pii.*"]
    if a.policy and os.path.isfile(a.policy):
        pol = json.load(open(a.policy, encoding="utf-8"))
        allow = pol.get("index_allowlist", allow)
        deny = pol.get("secret_denylist", deny)
    d = handle(a.query, a.root, allow, deny)
    print(json.dumps(asdict(d), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
