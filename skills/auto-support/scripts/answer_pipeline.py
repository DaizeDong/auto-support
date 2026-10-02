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

`generate` is injected for controlled integrations. Every accepted response must still be a
literal retrieved excerpt; free paraphrases require a separate verified integration. The default extractor returns ONLY retrieved public snippets with
citations. Separating large prose chapters also requires a semantic scope interpretation.
The test suite intercepts that model transport, preserving offline execution while exercising
the production source binding, dependency closure and answer gates.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Callable
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrails as G            # noqa: E402
import retrieval as R            # noqa: E402
import grounding as GR           # noqa: E402
import egress_dlp as E           # noqa: E402
import policy as P               # noqa: E402

INTENTS = ("product_usage_question", "chitchat", "off_topic", "sensitive_or_injection", "unclear")
_CHITCHAT = ("hi", "hello", "hey", "thanks", "thank you", "lol", "gm", "good morning", "ty")
_GREETING_PREFIX = re.compile(
    r"^(?:" + "|".join(re.escape(word) for word in _CHITCHAT) + r")(?:[\s!?,.;:，。！？]+|$)",
    re.IGNORECASE,
)
_PRODUCT_HINTS = ("how", "where", "what", "why", "can i", "does", "setup", "install", "config",
                  "error", "use", "api", "rate limit", "pricing", "docs", "feature", "support")


@dataclass
class Decision:
    decision: str                # answered | abstain | escalate | blocked-leak | cancelled
    intent: str
    trigger: str = ""
    response_text: str = ""      # grounded draft, OR neutral refusal, user-safe either way
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
    greeting = _GREETING_PREFIX.match(q)
    content = q[greeting.end():] if greeting else q
    if greeting and not content:
        return "chitchat"
    if any(h in content for h in (*_PRODUCT_HINTS, "如何", "怎么", "安装", "配置", "错误", "文档")) or content.endswith(("?", "？")):
        return "product_usage_question"
    if greeting and len(q) < 30:
        return "chitchat"
    return "unclear"


def _default_generate(query: str, snippets: list[GR.Snippet]) -> dict:
    """Deterministic grounded extractor: emit ONLY complete public source spans with their
    citation embedded so the grounding gate can verify the literal excerpt."""
    sents, cites = [], []
    for s in snippets:
        if not s.text.strip():
            continue
        sents.append(GR.render_excerpt(s))
        cites.append("%s:%d" % (s.path, s.line))
    return {
        "response_text": "\n".join(sents),
        "needs_escalation": False,
        "cited_sources": cites,
        "cited_internal_paths": [],     # canary, stays empty
        "contains_secret": False,       # canary, stays false
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
    # Greetings add no product evidence requirements; injection checked the full query.
    lookup_query = _GREETING_PREFIX.sub("", query.strip(), count=1)
    raw = R.search(root, lookup_query, allowlist, denylist)
    if not getattr(raw, "complete", True):
        return Decision("escalate", intent, trigger="no_evidence",
                        response_text=E.NEUTRAL_REFUSAL, reasons=["retrieval:incomplete_units"])
    snippets = [GR.Snippet(s.path, s.line, s.text, getattr(s, "required_citations", ())) for s in raw]
    if not snippets:
        return Decision("escalate", intent, trigger="no_evidence",
                        response_text=E.NEUTRAL_REFUSAL, reasons=["retrieval:empty"])

    # ---- Gate 3a: generation (grounded-only) ----
    answer = generate(query, snippets)
    # Validate structure before consuming model-provided fields. Only unchanged
    # excerpts have an executable faithfulness proof in this draft implementation.
    eg = E.evaluate(answer, allowlist=allowlist, denylist=denylist)
    if not eg.allowed:
        leak = any(r.startswith(("secret:", "pii:", "canary:")) or r == "markdown-exfil-channel" for r in eg.reasons)
        return Decision("blocked-leak" if leak else "escalate", intent,
                        trigger="suspected_leak" if leak else "egress_block",
                        response_text=E.NEUTRAL_REFUSAL, reasons=["egress:" + r for r in eg.reasons])
    if eg.escalate:
        return Decision("escalate", intent, trigger="generation_escalation",
                        response_text=E.NEUTRAL_REFUSAL)
    literal = GR.literal_citations(eg.response_text, snippets)
    if literal is None or set(answer.get("cited_sources", [])) != literal:
        return Decision("escalate", intent, trigger="unverified_generation",
                        response_text=E.NEUTRAL_REFUSAL, reasons=["grounding:literal_evidence_required"])

    # ---- Gate 3b: grounding (have-evidence-or-abstain) ----
    g = GR.classify(lookup_query, answer.get("response_text", ""), snippets,
                    retrieval_min, faithfulness_min, high_band)
    if not g.grounded:
        return Decision("escalate", intent, trigger="low_confidence",
                        response_text=E.NEUTRAL_REFUSAL,
                        retrieval_confidence=g.retrieval_confidence, faithfulness=g.faithfulness,
                        reasons=["grounding:low band=%s" % g.band])

    # passed all four gates -> DRAFT (MVP: goes to founder review, not auto-sent)
    return Decision("answered", intent, trigger="",
                    response_text=eg.response_text,
                    retrieval_confidence=g.retrieval_confidence, faithfulness=g.faithfulness,
                    citations=sorted(literal))


def main():
    import argparse, json
    ap = argparse.ArgumentParser(description="run the auto-support four-gate pipeline on one message")
    ap.add_argument("--root", help="public product root; must match the selected policy")
    ap.add_argument("--query", required=True)
    ap.add_argument("--policy")
    ap.add_argument("--demo", action="store_true", help="explicitly use built-in draft defaults")
    a = ap.parse_args()
    selected = a.policy or os.environ.get("AUTO_SUPPORT_POLICY")
    if a.demo and selected:
        ap.error("--demo cannot override an explicit policy or AUTO_SUPPORT_POLICY")
    try:
        if selected:
            pol = P.load_policy(selected)
            root = P.resolve_product_root(selected, pol)
            if a.root and Path(a.root).expanduser().resolve() != root:
                raise P.PolicyError("--root does not match the selected product policy")
            allow, deny = pol["index_allowlist"], pol["secret_denylist"]
            thresholds = {key: pol["confidence"][key] for key in P.DEFAULT_CONFIDENCE}
        elif a.demo and a.root:
            root = Path(a.root).expanduser().resolve()
            if not root.is_dir():
                raise P.PolicyError("demo root directory does not exist")
            allow, deny, thresholds = P.DEFAULT_ALLOW, P.DEFAULT_DENY, P.DEFAULT_CONFIDENCE
        else:
            ap.error("select --policy (or AUTO_SUPPORT_POLICY); use --demo --root only for a demo")
    except P.PolicyError as exc:
        ap.error(str(exc))
    # This command always returns a draft. Delivery modes are deployment capabilities.
    d = handle(a.query, str(root), allow, deny, **thresholds)
    # ASCII JSON preserves Unicode through escapes on legacy Windows consoles too.
    print(json.dumps(asdict(d), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
