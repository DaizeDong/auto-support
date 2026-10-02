"""Markdown procedure context stays complete across standard block forms."""
import pytest

import answer_pipeline as AP
import retrieval as R
from test_review_acceptance_a import fixtures


STYLES = [
    "spaces", "tab", "mixed-indent", "quote-tight", "quote-spaced", "quote-nested", "quote-lazy",
    "bullet-empty", "ordered-empty", "tilde-fence", "backtick-fence", "nested-heading",
    "html-block", "table", "emphasis", "thematic-break", "reference-definition",
]


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("oversized", [False, True], ids=["bounded", "oversized"])
def test_markdown_preparation_is_retained_or_the_whole_procedure_refuses(tmp_path, style, newline, oversized):
    relative, content, preparation = fixtures.markdown_preparation_case(tmp_path, style, oversized, newline)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    if oversized:
        assert len(preparation) > 4000
        assert result.decision != "answered", result
        assert result.faithfulness < 1.0
        assert "acme setup" not in result.response_text
    else:
        assert result.decision == "answered", result
        assert preparation in result.response_text
        assert result.response_text.index(preparation) < result.response_text.index("acme setup")
        assert all(citation.startswith(relative + ":") for citation in result.citations)
        for snippet in R.search(str(tmp_path), "install SDK", ["docs/**"], []):
            source = "".join(content.splitlines(keepends=True)[snippet.line - 1:])
            assert source.startswith(snippet.text)
            assert snippet.text in result.response_text
