"""Procedure completeness and emitted-evidence relevance regression contracts."""
import pytest

import answer_pipeline as AP
import grounding as GR
import retrieval as R
from test_review_acceptance_a import fixtures


@pytest.mark.parametrize("kind", [
    "condition-before", "condition-after", "multilingual", "numbered", "long-procedure", "crlf", "large",
])
def test_complete_sibling_procedure_preserved_without_keyword_overlap(tmp_path, kind):
    relative, content = fixtures.procedure_case(tmp_path, kind)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    assert result.decision == "answered", result
    if kind == "multilingual":
        assert "La cola permanece vacía durante esta operación." in result.response_text
    elif kind in ("numbered", "long-procedure"):
        assert result.response_text.index("Pause queue") < result.response_text.index("acme setup")
        assert result.response_text.index("acme setup") < result.response_text.index("Resume queue")
        if kind == "long-procedure":
            assert all("Confirm phase %d completed." % number in result.response_text for number in range(2, 9))
    else:
        assert "Execution is restricted to an idle worker pool." in result.response_text
    if kind == "large":
        assert len(content) > 8000 and len(result.response_text) < 4000
        assert "Resume queue consumption." in result.response_text
    for snippet in R.search(str(tmp_path), "install SDK", ["docs/**"], []):
        source = "".join(content.splitlines(keepends=True)[snippet.line - 1:])
        assert source.startswith(snippet.text)
        assert snippet.text in result.response_text
    assert all(citation.startswith(relative + ":") for citation in result.citations)


def test_oversized_surrounding_procedure_cannot_be_silently_dropped(tmp_path):
    fixtures.procedure_case(tmp_path, "oversized-context")
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    assert result.decision != "answered"
    assert result.faithfulness < 1.0


@pytest.mark.parametrize("selected,answerable", [("docs/export.md", True), ("docs/appearance.md", False)])
def test_only_emitted_document_can_supply_query_relevance(tmp_path, selected, answerable):
    records = fixtures.subset_relevance_case(tmp_path)
    query = "How do I export audit reports?"

    def choose(query, snippets):
        return AP._default_generate(query, [snippet for snippet in snippets if snippet.path == selected])

    result = AP.handle(query, str(tmp_path), ["docs/**"], [], generate=choose)
    assert (result.decision == "answered") is answerable
    if answerable:
        assert records[selected] in result.response_text
        assert result.citations == [selected + ":1"]
    else:
        assert result.retrieval_confidence < 0.7


def test_grounding_classification_uses_emitted_evidence_only(tmp_path):
    fixtures.subset_relevance_case(tmp_path)
    query = "How do I export audit reports?"
    snippets = R.search(str(tmp_path), query, ["docs/**"], [])
    selected = [snippet for snippet in snippets if snippet.path == "docs/appearance.md"]
    answer = AP._default_generate(query, selected)["response_text"]
    result = GR.classify(query, answer, snippets)
    assert not result.grounded
    assert result.retrieval_confidence < 0.7
