#!/usr/bin/env python3
"""auto-support — egress gate (Layer 4): the last fail-closed line before anything is sent.

Even after retrieval + grounding, the final candidate is structure-checked and DLP-scanned.
The answer MUST be a structured object; free-text leakage is physically constrained by the
schema (architecture 2.3):

    {
      "response_text": str,
      "needs_escalation": bool,
      "cited_sources": [ "path:line", ... ],   # public allowlisted refs only
      "cited_internal_paths": [],              # CANARY: must be empty; non-empty = policy violation
      "contains_secret": false                 # CANARY: must be false
    }

block (fail-closed) if ANY of: schema invalid, canary field tripped, secret/PII/exfil-link in
response_text or citations, citation points outside the allowlist, or no citation at all for a
substantive answer. On block we emit the single neutral refusal line (never the reason -> no
boundary probing) and signal escalation.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import guardrails as G  # noqa: E402

NEUTRAL_REFUSAL = "这个问题我无法确定，已转交团队跟进。"  # never reveal WHY (no boundary probing)
_CITE = re.compile(r"^[^:\s]+(?:/[^:\s]+)*:\d+$")


@dataclass
class EgressDecision:
    allowed: bool
    response_text: str               # safe text to send, OR the neutral refusal on block
    reasons: list[str] = field(default_factory=list)   # internal only; never shown to user
    escalate: bool = False


def _valid_schema(ans: dict) -> list[str]:
    errs = []
    if not isinstance(ans, dict):
        return ["not-an-object"]
    if not isinstance(ans.get("response_text", None), str):
        errs.append("response_text-missing")
    if not isinstance(ans.get("cited_sources", []), list):
        errs.append("cited_sources-type")
    # canary fields — their whole job is to be tripped by a misbehaving generator
    if ans.get("cited_internal_paths"):
        errs.append("canary:cited_internal_paths-nonempty")
    if ans.get("contains_secret", False):
        errs.append("canary:contains_secret-true")
    return errs


def evaluate(answer: dict, allowlist=None, denylist=None, require_citation: bool = True) -> EgressDecision:
    reasons = _valid_schema(answer)
    if reasons:
        return EgressDecision(False, NEUTRAL_REFUSAL, reasons, escalate=True)

    text = answer.get("response_text", "")
    cites = answer.get("cited_sources", []) or []

    # 1) DLP on the visible text (+ citations string-joined)
    blob = text + "\n" + "\n".join(map(str, cites))
    leak = G.egress_leak_verdict(blob)
    if not leak.safe:
        reasons += leak.reasons

    # 2) citation integrity: format + inside allowlist (if a policy is provided)
    for c in cites:
        if not _CITE.match(str(c)):
            reasons.append("bad-citation-format:%s" % c)
            continue
        if allowlist is not None:
            path = str(c).rsplit(":", 1)[0]
            v = G.path_verdict(path, allowlist, denylist or [])
            if not v.allowed:
                reasons.append("citation-outside-allowlist:%s" % path)

    # 3) substantive answer must cite something (no ungrounded prose)
    if require_citation and len(text.strip()) > 40 and not cites:
        reasons.append("substantive-answer-without-citation")

    # 4) no markdown image/link carrying project data outbound
    if re.search(r"!\[[^\]]*\]\([^)]+\)", text) or re.search(r"\]\(\s*https?://[^)]*\?[^)]*=", text):
        reasons.append("markdown-exfil-channel")

    if reasons:
        return EgressDecision(False, NEUTRAL_REFUSAL, reasons, escalate=True)
    return EgressDecision(True, text, [], escalate=bool(answer.get("needs_escalation")))


def main():
    ans = json.loads(sys.stdin.read() or "{}")
    d = evaluate(ans)
    # never print `reasons` to a user-facing channel; here it's a CLI diagnostic only
    print(json.dumps({"allowed": d.allowed, "response_text": d.response_text,
                      "escalate": d.escalate, "reasons": d.reasons}, ensure_ascii=False, indent=2))
    return 0 if d.allowed else 1


if __name__ == "__main__":
    sys.exit(main())
