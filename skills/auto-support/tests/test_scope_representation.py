"""Local context and explicit source dependencies have separate scope evidence."""
import hashlib

import pytest

import answer_pipeline as AP
import retrieval as R
from test_review_acceptance_a import fixtures


@pytest.mark.parametrize('kind', ['local-before', 'local-after'])
@pytest.mark.parametrize('newline', ['\n', '\r\n'], ids=['lf', 'crlf'])
def test_local_preamble_does_not_make_unrelated_chapter_mandatory(tmp_path, kind, newline):
    relative, content, preamble = fixtures.scoped_document_case(tmp_path, kind, newline)
    result = AP.handle('How do I install the SDK?', str(tmp_path), ['docs/**'], [])
    assert len(content) > 6000
    assert result.decision == 'answered', result
    assert preamble in result.response_text
    assert 'acme setup' in result.response_text
    assert len(result.response_text) < 4000
    assert 'Background material about typography.' not in result.response_text
    for snippet in R.search(str(tmp_path), 'install SDK', ['docs/**'], []):
        assert ''.join(content.splitlines(keepends=True)[snippet.line-1:]).startswith(snippet.text)
        assert snippet.text in result.response_text
        assert snippet.path == relative


@pytest.mark.parametrize('newline', ['\n', '\r\n'], ids=['lf', 'crlf'])
def test_explicit_whole_document_scope_remains_required(tmp_path, newline):
    fixtures.scoped_document_case(tmp_path, 'document-scope', newline)
    result = AP.handle('How do I install the SDK?', str(tmp_path), ['docs/**'], [])
    assert result.decision != 'answered'
    assert result.faithfulness < 1.0
    assert 'acme setup' not in result.response_text


@pytest.mark.parametrize('kind', ['reference-oversized', 'broken-reference'])
def test_explicit_dependency_cannot_be_missing_or_over_budget(tmp_path, kind):
    fixtures.scoped_document_case(tmp_path, kind)
    result = AP.handle('How do I install the SDK?', str(tmp_path), ['docs/**'], [])
    assert result.decision != 'answered'
    assert result.faithfulness < 1.0
    assert 'acme setup' not in result.response_text


@pytest.mark.parametrize('newline', ['\n', '\r\n'], ids=['lf', 'crlf'])
def test_reference_graph_binds_its_relations_to_exact_source(tmp_path, newline):
    relative, content, preamble = fixtures.scoped_document_case(tmp_path, 'reference', newline)
    result = R.search(str(tmp_path), 'install SDK', ['docs/**'], [])
    assert result.complete
    graph = result.scope_graphs[relative]
    assert graph.source_sha256 == hashlib.sha256(content.encode('utf-8')).hexdigest()
    assert graph.verify_source(content.splitlines(keepends=True))
    assert not graph.verify_source((content+'Altered source.\n').splitlines(keepends=True))
    dependencies = [edge for edge in graph.dependencies if edge.reason == 'markdown-reference']
    assert len(dependencies) == 1
    edge = dependencies[0]
    evidence = ''.join(content.splitlines(keepends=True)[edge.evidence.start:edge.evidence.end])
    assert '[operating envelope](#operating-envelope)' in evidence
    required = graph.required_sections({edge.source})
    assert edge.target in required
    answer = AP.handle('How do I install the SDK?', str(tmp_path), ['docs/**'], [])
    assert answer.decision == 'answered'
    assert preamble in answer.response_text
    assert 'idle worker pool and a verified checkpoint' in answer.response_text
    assert 'acme setup' in answer.response_text
