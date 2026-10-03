"""Public proof, fresh visibility and a second snapshot must all agree."""
from types import SimpleNamespace

import pytest

import runtime_data as D
from test_review_acceptance_a import fixtures


@pytest.mark.parametrize("change", [None, "root", "repositories", "signature", "proof-error",
                                    "second-proof-error", "public", "unknown", "query-error",
                                    "missing-head", "ignored", "ignore-error"])
def test_public_proof_and_live_visibility_are_required_before_admission(tmp_path, monkeypatch, change):
    root = tmp_path / "synthetic-companion"
    root.mkdir()
    original = fixtures.public_proof_case(root)
    calls = []
    proofs = []

    def prove(destination):
        assert destination == root
        calls.append("proof")
        if change == "proof-error" or (proofs and change == "second-proof-error"):
            raise RuntimeError("Synthetic proof unavailable")
        value = dict(original)
        if proofs and change in {"root", "repositories", "signature"}:
            value[change] = (("example-owner/changed-config",) if change == "repositories"
                             else str(root / "changed") if change == "root" else "changed-signature")
        proof = SimpleNamespace(**value)
        proofs.append(proof)
        return proof

    def query(argv, **kwargs):
        assert argv[:4] == ["gh", "api", "--hostname", "github.com"]
        assert argv[5:] == ["--jq", ".private"]
        assert argv[4] in {"repos/" + name for name in original["repositories"]}
        calls.append(argv[4])
        if change == "query-error":
            raise D.DataBoundaryError("Synthetic visibility query failed")
        return "false" if change == "public" else "null" if change == "unknown" else "true"

    def read(proof, *arguments):
        if arguments == ("rev-parse", "--verify", "HEAD"):
            calls.append("head")
            if change == "missing-head":
                raise RuntimeError("Synthetic repository has no committed history")
            return SimpleNamespace(returncode=0, stdout="synthetic-head")
        assert arguments == ("check-ignore", "--no-index", "-q", "--", "support.db")
        calls.append("ignore")
        return SimpleNamespace(returncode=0 if change == "ignored" else 7 if change == "ignore-error" else 1)

    monkeypatch.setattr(D, "_boundary_module", lambda: SimpleNamespace(
        prove_private_companion=prove, read_private_companion_git=read), raising=False)
    monkeypatch.setattr(D, "_run", query)
    if change:
        with pytest.raises(D.DataBoundaryError):
            D.private_file_path(root / "support.db")
    else:
        assert D.private_file_path(root / "support.db") == root / "support.db"
        assert calls == ["proof", "head", "ignore", *("repos/" + name for name in original["repositories"]), "proof"]
    if change == "proof-error":
        assert calls == ["proof"]
    assert list(root.iterdir()) == []
