"""Unavailable public evidence must not become a complete grounded draft."""
import builtins
import errno
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

import pytest

import answer_pipeline as AP
import retrieval as R
import pretooluse_hook as H
from test_review_acceptance_a import fixtures


def inject_fault(monkeypatch, target, kind):
    original_open = builtins.open
    original_fstat = os.fstat
    tracked = set()
    stats = 0
    observed = {"metadata_failures": 0, "target_opens": 0}

    class FailedRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def readlines(self):
            raise OSError(errno.EIO, "synthetic document read failure")

    def opened(path, *args, **kwargs):
        if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)) == target:
            observed["target_opens"] += 1
            if kind == "permission":
                raise PermissionError(errno.EACCES, "synthetic document permission failure")
            if kind == "missing":
                raise FileNotFoundError(errno.ENOENT, "synthetic document disappeared")
            stream = original_open(path, *args, **kwargs)
            tracked.add(stream.fileno())
            return FailedRead(stream) if kind == "read-error" else stream
        return original_open(path, *args, **kwargs)

    def fstat(descriptor):
        nonlocal stats
        if descriptor in tracked:
            stats += 1
            if kind == "handle-changed-before" or kind == "handle-changed-after" and stats >= 2:
                return SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=2)
        return original_fstat(descriptor)

    monkeypatch.setattr(builtins, "open", opened)
    monkeypatch.setattr(os, "fstat", fstat)
    if kind.startswith("inventory-"):
        original_scandir = os.scandir

        def scandir(path):
            if Path(path) == target.parent:
                code = errno.EACCES if kind == "inventory-permission" else errno.EIO
                raise OSError(code, "synthetic directory enumeration failure")
            return original_scandir(path)

        monkeypatch.setattr(os, "scandir", scandir)
    if kind.startswith("stat-"):
        original_stat = os.stat
        error_type, code = {
            "stat-permission": (PermissionError, errno.EACCES),
            "stat-io": (OSError, errno.EIO),
            "stat-missing": (FileNotFoundError, errno.ENOENT),
        }[kind]

        def metadata(path, *args, **kwargs):
            if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)) == target:
                observed["metadata_failures"] += 1
                raise error_type(code, "synthetic initial document metadata failure")
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(os, "stat", metadata)
    if kind == "admission-changed":
        original_admission = R.D.allowed_document
        calls = 0

        def allowed_document(path, **kwargs):
            nonlocal calls
            if Path(path) == target:
                calls += 1
                if calls > 1:
                    return False
            return original_admission(path, **kwargs)

        monkeypatch.setattr(R.D, "allowed_document", allowed_document)
    return observed


@pytest.mark.parametrize("kind", fixtures.retrieval_availability_cases())
@pytest.mark.parametrize("surface", ["search", "draft", "retrieval-cli"])
def test_unavailable_document_never_reports_complete(tmp_path, monkeypatch, capsys, kind, surface):
    case = fixtures.retrieval_availability_case(tmp_path, kind)
    observed = inject_fault(monkeypatch, case["target"], kind)
    if surface == "search":
        result = R.search(str(tmp_path), case["query"], ["docs/**"], [])
        if kind.startswith("stat-"):
            assert observed["metadata_failures"] and observed["target_opens"] == 0
        assert result.complete is case["complete"]
        if kind == "complete":
            assert any(case["prerequisite"] in snippet.text for snippet in result)
    elif surface == "draft":
        calls = []

        def generate(query, snippets):
            calls.append(query)
            return AP._default_generate(query, snippets)

        result = AP.handle(case["query"], str(tmp_path), ["docs/**"], [], generate=generate)
        if kind.startswith("stat-"):
            assert observed["metadata_failures"] and observed["target_opens"] == 0
        assert (result.decision == "answered") is case["complete"]
        assert bool(calls) is case["complete"]
        if kind == "complete":
            assert case["prerequisite"].strip() in result.response_text
            assert result.faithfulness == 1.0 and len(result.citations) == 2
        elif not case["complete"]:
            assert result.citations == [] and "acme.install()" not in result.response_text
    else:
        monkeypatch.setattr(sys, "argv", ["retrieval.py", "--demo", "--root", str(tmp_path), "--query", case["query"]])
        code = R.main()
        result = json.loads(capsys.readouterr().out)
        if kind.startswith("stat-"):
            assert observed["metadata_failures"] and observed["target_opens"] == 0
        assert code == (0 if case["complete"] else 2)
        assert result["complete"] is case["complete"]
        if not case["complete"]:
            assert result["snippets"] == []


@pytest.mark.parametrize("kind", [
    "complete", "inventory-permission", "inventory-io", "stat-permission", "stat-io", "stat-missing",
])
def test_list_files_reports_inventory_failure(tmp_path, monkeypatch, capsys, kind):
    case = fixtures.retrieval_availability_case(tmp_path, kind)
    inject_fault(monkeypatch, case["target"], kind)
    monkeypatch.setattr(sys, "argv", ["retrieval.py", "--demo", "--root", str(tmp_path), "--list-files"])
    code = R.main()
    output = capsys.readouterr()
    if case["complete"]:
        assert code == 0 and len(json.loads(output.out)) == 2
    else:
        assert code == 2 and not output.out.strip() and "incomplete" in output.err



@pytest.mark.parametrize("kind", ["stat-permission", "stat-io", "stat-missing"])
def test_metadata_failure_preserves_hook_boundary(tmp_path, monkeypatch, kind):
    case = fixtures.retrieval_availability_case(tmp_path, kind)
    observed = inject_fault(monkeypatch, case["target"], kind)
    allowed = H._bounded_path(str(case["target"]), tmp_path, tmp_path, ["docs/**"], [])
    assert allowed is (kind == "stat-missing")
    assert observed["metadata_failures"] and observed["target_opens"] == 0
