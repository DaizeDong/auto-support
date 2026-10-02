"""Complete procedure scope cannot be inferred from absent lexical matches."""
import pytest

import answer_pipeline as AP
from test_review_acceptance_a import fixtures


@pytest.mark.parametrize("position", ["before", "after"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_oversized_semantic_prerequisite_cannot_be_omitted(tmp_path, position, newline):
    fixtures.semantic_scope_case(tmp_path, "required", position, newline)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    assert result.decision != "answered", result
    assert "acme setup" not in result.response_text
    assert result.faithfulness < 1.0


@pytest.mark.parametrize("position", ["before", "after"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_oversized_unrelated_prose_keeps_bounded_procedure_usable(tmp_path, position, newline):
    relative, content, unrelated = fixtures.semantic_scope_case(tmp_path, "unrelated", position, newline)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    assert len(content) > 6000
    assert result.decision == "answered", result
    assert "acme setup" in result.response_text
    assert "Resume processing." in result.response_text
    assert unrelated not in result.response_text
    assert len(result.response_text) < 4000
    assert all(citation.startswith(relative + ":") for citation in result.citations)


@pytest.mark.parametrize("fault", ["unavailable", "transport-error", "uncertain", "wrong-source", "missing-pair",
                                  "duplicate-pair", "wrong-range", "unknown-section"])
def test_unproved_independence_never_allows_partial_answer(tmp_path, semantic_model, monkeypatch, fault):
    fixtures.semantic_scope_case(tmp_path, "unrelated", "before")
    interpret = semantic_model.call

    def corrupt(prompt, **kwargs):
        if fault == "transport-error":
            raise TimeoutError("Synthetic transport failure")
        response = interpret(prompt, **kwargs)
        if fault == "unavailable":
            response.data = None
            response.provider = None
        elif fault == "uncertain":
            response.data["relations"][-1]["relation"] = "uncertain"
        elif fault == "wrong-source":
            response.data["source_sha256"] = "0" * 64
        elif fault == "missing-pair":
            response.data["relations"].pop()
        elif fault == "duplicate-pair":
            response.data["relations"].append(response.data["relations"][0])
        elif fault == "wrong-range":
            response.data["relations"][0]["evidence"][0]["end"] += 1
        elif fault == "unknown-section":
            response.data["relations"][0]["right"] = 999
        return response

    monkeypatch.setattr(semantic_model, "call", corrupt)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    assert result.decision != "answered", result
    assert "acme setup" not in result.response_text
    assert result.faithfulness < 1.0


@pytest.mark.parametrize("contamination", ["pii", "secret", "injection"])
def test_unsafe_whole_document_never_reaches_scope_model(tmp_path, semantic_model, monkeypatch, contamination):
    fixtures.semantic_scope_case(tmp_path, "unrelated", "after", contamination=contamination)
    interpret = semantic_model.call
    requests = []

    def record(prompt, **kwargs):
        requests.append(prompt)
        return interpret(prompt, **kwargs)

    monkeypatch.setattr(semantic_model, "call", record)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    assert result.decision != "answered", result
    assert not requests, "Unsafe source text reached the semantic transport boundary"
