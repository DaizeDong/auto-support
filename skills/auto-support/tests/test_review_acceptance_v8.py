"""Explicit prose dependencies cannot disappear at a peer-section size boundary."""
import pytest

import answer_pipeline as AP
import retrieval as R
from test_review_acceptance_a import fixtures


@pytest.mark.parametrize("kind", [
    "required-title", "required-paragraph", "named-reference", "later-reference",
    "preamble-scope", "bridge-run", "unrelated", "unrelated-appendix",
])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("oversized", [False, True], ids=["bounded", "oversized"])
def test_prose_dependency_boundary(tmp_path, kind, newline, oversized):
    relative, content, preparation = fixtures.prose_dependency_case(tmp_path, kind, oversized, newline)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    unrelated = kind in {"unrelated", "unrelated-appendix"}
    if oversized and not unrelated:
        assert len(preparation) > 4000
        assert result.decision != "answered", result
        assert result.faithfulness < 1.0
        assert "acme setup" not in result.response_text
    else:
        assert result.decision == "answered", result
        assert "acme setup" in result.response_text
        if not unrelated:
            assert preparation in result.response_text
        if oversized:
            assert len(result.response_text) < 4000
        assert all(citation.startswith(relative + ":") for citation in result.citations)
        for snippet in R.search(str(tmp_path), "install SDK", ["docs/**"], []):
            source = "".join(content.splitlines(keepends=True)[snippet.line - 1:])
            assert source.startswith(snippet.text)
