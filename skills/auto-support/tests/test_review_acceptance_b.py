"""Complete instruction and inode-boundary regressions from synthetic sources."""
import builtins
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import answer_pipeline as AP
import grounding as GR
import retrieval as R
from test_review_acceptance_a import fixtures
from test_first_run_contract import HOOK


@pytest.mark.parametrize("kind", ["fenced", "plain", "large", "inherited", "adjacent", "crlf"])
def test_answer_retains_complete_command_and_mandatory_context(tmp_path, kind):
    relative, content = fixtures.instruction_case(tmp_path, kind)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    assert result.decision == "answered", result
    assert "create a recoverable backup" in result.response_text
    assert "--endpoint https://example.com/sdk" in result.response_text
    assert "--timeout 37" in result.response_text
    assert "successful exit is required" in result.response_text
    assert result.faithfulness == 1.0
    for snippet in R.search(str(tmp_path), "install SDK", ["docs/**"], []):
        source = "".join(content.splitlines(keepends=True)[snippet.line - 1:])
        assert source.startswith(snippet.text)
        assert snippet.text in result.response_text
    assert all(citation.startswith(relative + ":") for citation in result.citations)
    if kind == "large":
        assert len(content) > 8000
        assert len(result.response_text) < 4000
    if kind == "crlf":
        assert content in result.response_text


@pytest.mark.parametrize("kind", ["over-budget", "unsafe-context"])
def test_unusable_mandatory_context_does_not_produce_partial_answer(tmp_path, kind):
    fixtures.instruction_case(tmp_path, kind)
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [])
    assert result.decision != "answered"
    assert result.faithfulness != 1.0


def test_generator_cannot_drop_inherited_prerequisite(tmp_path):
    fixtures.instruction_case(tmp_path, "inherited")

    def omit_context(query, snippets):
        return AP._default_generate(query, [s for s in snippets if "--timeout" in s.text])

    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [],
                       generate=omit_context)
    assert result.decision != "answered"


def test_generator_cannot_move_prerequisites_after_the_command(tmp_path):
    fixtures.instruction_case(tmp_path, "inherited")
    result = AP.handle("How do I install the SDK?", str(tmp_path), ["docs/**"], [],
                       generate=lambda query, snippets: AP._default_generate(query, list(reversed(snippets))))
    assert result.decision != "answered"


def test_standalone_faithfulness_rejects_missing_required_context(tmp_path):
    fixtures.instruction_case(tmp_path, "inherited")
    snippets = R.search(str(tmp_path), "install SDK", ["docs/**"], [])
    main = [s for s in snippets if "--timeout" in s.text]
    answer = AP._default_generate("install SDK", main)["response_text"]
    assert GR.faithfulness(answer, snippets)[0] < 1.0


def test_descriptor_recheck_rejects_link_created_after_path_admission(tmp_path, monkeypatch):
    root, alias, outside = fixtures.linked_document_case(tmp_path, linked=False)
    original_open = builtins.open

    def link_before_open(path, *args, **kwargs):
        if isinstance(path, (str, os.PathLike)) and Path(path) == alias:
            outside.unlink()
            outside.hardlink_to(alias)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", link_before_open)
    assert R.search(str(root), "install SDK", ["docs/**"], []) == []


@pytest.mark.parametrize("max_snippets,max_chars", [(0, 4000), (5, 50), (1, 4000)])
def test_budget_never_cuts_an_instruction_or_its_context(tmp_path, max_snippets, max_chars):
    fixtures.instruction_case(tmp_path, "inherited")
    snippets = R.search(str(tmp_path), "install SDK", ["docs/**"], [],
                        max_snippets=max_snippets, max_chars=max_chars)
    assert len(snippets) <= max_snippets
    assert sum(len(s.text) for s in snippets) <= max_chars
    assert not snippets


def test_hardlinked_public_alias_is_rejected_before_reading(tmp_path, monkeypatch):
    root, alias, outside = fixtures.linked_document_case(tmp_path)
    assert alias.stat().st_nlink > 1 and alias.samefile(outside)
    original_open = builtins.open

    def reject_alias_read(path, *args, **kwargs):
        if isinstance(path, (str, os.PathLike)) and Path(path) == alias:
            pytest.fail("retrieval attempted to open a multiply linked document")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", reject_alias_read)
    assert R.allowed_files(str(root), ["docs/**"], []) == []
    assert R.search(str(root), "install SDK", ["docs/**"], []) == []
    assert AP.handle("How do I install the SDK?", str(root), ["docs/**"], []).decision != "answered"


@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "cat", "head", "tail"])
def test_hook_enforces_inode_boundary_for_every_read_path(tmp_path, linked, tool):
    root, alias, _ = fixtures.linked_document_case(tmp_path, linked)
    if tool == "Read":
        inputs = {"file_path": str(alias)}
    elif tool in {"Grep", "Glob"}:
        inputs = {"path": str(alias.parent), "pattern": "setup" if tool == "Grep" else "*.md"}
    else:
        inputs = {"command": tool + ' "' + alias.as_posix() + '"'}
    event = fixtures.hook_event(tool if tool in {"Read", "Grep", "Glob"} else "Bash",
                                inputs, cwd=str(root))
    # The default policy root is the hook subprocess working directory.
    env = {key: value for key, value in os.environ.items() if not key.startswith("AUTO_SUPPORT_")}
    result = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(event),
                            capture_output=True, text=True, encoding="utf-8", cwd=root,
                            env=env, timeout=20)
    assert result.returncode == (2 if linked else 0), result.stderr
