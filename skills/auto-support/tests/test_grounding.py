"""Grounding gate: have-evidence-or-abstain."""
import grounding as GR


def _snips():
    return [GR.Snippet("public-faq/faq.md", 4,
                       "The public rate limit is 100 requests per minute per API key.")]


def test_grounded_answer_with_citation_passes():
    # citation embedded IN the sentence (matches the generator's output form)
    ans = "The public rate limit is 100 requests per minute per API key [public-faq/faq.md:4]."
    g = GR.classify("what is the rate limit?", ans, _snips())
    assert g.grounded and g.faithfulness == 1.0


def test_uncited_claim_is_ungrounded():
    ans = "The rate limit is actually 1,000,000 requests per second."  # no citation, fabricated
    g = GR.classify("what is the rate limit?", ans, _snips())
    assert not g.grounded


def test_fabricated_citation_is_ungrounded():
    ans = "The limit is 100 per minute [internal/secret.md:99]."  # cite points outside retrieval
    g = GR.classify("rate limit", ans, _snips())
    assert not g.grounded


def test_empty_retrieval_low_confidence():
    g = GR.classify("rate limit", "anything [x:1].", [])
    assert g.band == "low" and not g.grounded
