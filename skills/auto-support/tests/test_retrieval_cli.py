"""The retrieval CLI must disclose completeness and suppress partial evidence."""
import json
import sys

import pytest

import retrieval as R
from test_review_acceptance_a import fixtures


def run_cli(root, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["retrieval.py", "--demo", "--root", str(root), "--query", "install"])
    result = R.main()
    output = capsys.readouterr()
    return result, json.loads(output.out)


def test_complete_matches_have_a_successful_explicit_result(tmp_path, monkeypatch, capsys):
    fixtures.retrieval_completeness_case(tmp_path, "complete")
    status, output = run_cli(tmp_path, monkeypatch, capsys)
    assert status == 0
    assert output["complete"] is True
    assert {item["path"] for item in output["snippets"]} == {"docs/install.md", "docs/options.md"}
    assert output["snippets"][0]["text"] == "Install the Acme SDK with `acme setup`.\n"


@pytest.mark.parametrize("kind", ["over-budget", "unfinished"])
def test_mixed_usable_and_incomplete_matches_refuse_without_partial_evidence(tmp_path, monkeypatch, capsys, kind):
    fixtures.retrieval_completeness_case(tmp_path, kind)
    partial = R.search(str(tmp_path), "install", ["docs/**"], [])
    assert partial and not partial.complete
    status, output = run_cli(tmp_path, monkeypatch, capsys)
    assert status == 2
    assert output == {"complete": False, "snippets": []}
