"""Shared deterministic terms for English and Chinese public-document lookup."""
import re

STOP = set("the a an is are was were be do does did how what why when where which who you your yours i me my we our to of for and or in on with this that it its can could please tell give get about from into any".split())


def content_terms(text):
    normalized = (text or "").lower()
    for filler in ("请问", "告诉我", "如何", "怎么", "怎样", "是否", "什么"):
        normalized = normalized.replace(filler, " ")
    terms = {word for word in re.findall(r"[a-z0-9]+", normalized) if len(word) > 2 and word not in STOP}
    for chunk in re.findall(r"[\u3400-\u9fff]+", normalized):
        if len(chunk) == 1:
            terms.add(chunk)
        else:
            terms.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
    return terms
