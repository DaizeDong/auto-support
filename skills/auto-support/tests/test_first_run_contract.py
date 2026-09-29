"""Cold-start and literal-evidence regressions using generated local inputs."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import answer_pipeline as pipeline
import grounding
import retrieval
import policy as policy_schema


REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "scripts"
PIPELINE = REPO / "skills/auto-support/scripts/answer_pipeline.py"
HOOK = PIPELINE.with_name("pretooluse_hook.py")


def run_script(path, *args, input_text=None, env=None):
    isolated = {k: v for k, v in os.environ.items() if not k.startswith("AUTO_SUPPORT_")}
    isolated.update(env or {})
    return subprocess.run(
        [sys.executable, "-B", str(path), *map(str, args)],
        input=input_text, capture_output=True, text=True, encoding="utf-8",
        env=isolated, timeout=20,
    )


@pytest.mark.parametrize("source", [
    "Use `client.ping()` to install the synthetic SDK.",
    "The synthetic timeout is 2.5 seconds. Retry `client.ping()` once.",
    'Use `print("hello! world")`. See https://example.com/a?test=1.',
])
def test_default_extractor_preserves_source_and_grounding(source):
    snippets = [grounding.Snippet("docs/example.md", 7, source)]
    answer = pipeline._default_generate("synthetic", snippets)["response_text"]
    assert source in answer
    assert grounding.faithfulness(answer, snippets) == (1.0, [])


def test_literal_excerpt_does_not_license_appended_uncited_claim():
    source = "The synthetic limit is 100 requests."
    snippets = [grounding.Snippet("docs/example.md", 7, source)]
    answer = source + " [docs/example.md:7]\nThe limit is 9000 requests."
    confidence, unsupported = grounding.faithfulness(answer, snippets)
    assert confidence < 1.0
    assert any("9000" in part for part in unsupported)


def test_valid_citation_cannot_hide_fabricated_second_citation():
    snippets = [grounding.Snippet("docs/example.md", 7, "The limit is 100 requests.")]
    assert grounding.faithfulness("The limit is 100 requests [docs/example.md:7] [docs/missing.md:1].", snippets)[0] == 0


@pytest.mark.parametrize("claim", ["2", "25", "0.25"])
def test_changed_numeric_claim_is_not_grounded(claim):
    snippets = [grounding.Snippet("docs/example.md", 7, "The timeout is 2.5 seconds.")]
    assert grounding.faithfulness(f"The timeout is {claim} seconds [docs/example.md:7].", snippets)[0] == 0


def test_one_unsupported_claim_rejects_whole_draft():
    snippets = [grounding.Snippet("docs/example.md", 7, "The synthetic limit is 100 requests.")]
    text = "\n".join([pipeline._default_generate("limit", snippets)["response_text"]] * 4)
    text += "\nThe limit is 9000 requests."
    assert not grounding.classify("limit", text, snippets).grounded


def test_init_adds_product_without_overwriting_existing_config(tmp_path):
    companion = tmp_path / "synthetic-companion"
    assert run_script(SCRIPTS / "init_config.py", "--slug", "first", "--out", companion).returncode == 0
    policy = companion / "products/first/policy.json"
    original = policy.read_bytes()
    assert run_script(SCRIPTS / "init_config.py", "--slug", "second", "--out", companion).returncode == 0
    assert policy.read_bytes() == original
    assert json.loads((companion / "registry.json").read_text())["products"] == ["first", "second"]


def test_draft_pipeline_uses_selected_product_and_confidence(tmp_path):
    companion = tmp_path / "synthetic-companion"
    assert run_script(SCRIPTS / "init_config.py", "--out", companion).returncode == 0
    root = tmp_path / "public-docs"
    root.mkdir()
    (root / "README.md").write_text("Install the synthetic SDK with `client.ping()`.", encoding="utf-8")
    product_path = companion / "products/example/product.json"
    product = json.loads(product_path.read_text())
    product["product_root"] = str(root)
    product_path.write_text(json.dumps(product))
    policy_path = product_path.with_name("policy.json")
    result = run_script(PIPELINE, "--policy", policy_path, "--query", "How do I install the SDK?")
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout)
    assert answer["decision"] == "answered"
    assert "client.ping()" in answer["response_text"]
    # Low evidence coverage is rejected by the selected high threshold.
    policy = json.loads(policy_path.read_text())
    policy["confidence"] = {"retrieval_min": 1.0, "faithfulness_min": 1.0, "high_band": 1.0}
    policy_path.write_text(json.dumps(policy))
    result = run_script(PIPELINE, "--policy", policy_path, "--query", "How do I install the SDK backwards?")
    assert result.returncode == 0
    assert json.loads(result.stdout)["decision"] != "answered"
    result = run_script(PIPELINE, "--policy", policy_path, "--root", tmp_path, "--query", "SDK?")
    assert result.returncode != 0


@pytest.mark.parametrize("command", [
    "echo hello; uname", "echo hello && env", "echo $(env)", "echo `env`",
    "cat docs/usage.md | env", "ls", "cat README.md .profile", "sed -i docs/usage.md",
    "cat docs/usage.md\nwhoami", "echo $SECRET", "ls src", "cat -- /etc/passwd",
])
def test_hook_rejects_shell_interpretation_and_unbounded_reads(command):
    result = run_script(HOOK, input_text=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}))
    assert result.returncode == 2


def test_chinese_query_finds_cited_public_instructions(tmp_path):
    (tmp_path / "README.md").write_text("安装 SDK 时调用 `client.ping()`。", encoding="utf-8")
    result = pipeline.handle("如何安装 SDK？", str(tmp_path), policy_schema.DEFAULT_ALLOW, policy_schema.DEFAULT_DENY)
    assert result.decision == "answered"
    assert "client.ping()" in result.response_text
    assert "README.md:1" in result.response_text


def test_retrieval_does_not_read_allowed_alias_to_private_target(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    public_alias = docs / "alias.md"
    public_alias.write_text("synthetic alias", encoding="utf-8")
    private = tmp_path / "internal"
    private.mkdir()
    target = private / "details.md"
    target.write_text("private synthetic secret", encoding="utf-8")
    realpath = os.path.realpath
    monkeypatch.setattr(os.path, "realpath", lambda p: str(target) if Path(p) == public_alias else realpath(p))
    assert retrieval.allowed_files(str(tmp_path), policy_schema.DEFAULT_ALLOW, policy_schema.DEFAULT_DENY) == []


@pytest.mark.parametrize("policy_text", [None, "{", "[]", "{}",
    '{"index_allowlist":["README*"],"secret_denylist":[]}',
])
def test_explicit_invalid_policy_stops_before_answering(tmp_path, policy_text):
    root = tmp_path / "synthetic-product"
    root.mkdir()
    (root / "README.md").write_text("Install the synthetic SDK with `client.ping()`.", encoding="utf-8")
    policy = tmp_path / "policy.json"
    if policy_text is not None:
        policy.write_text(policy_text, encoding="utf-8")
    result = run_script(PIPELINE, "--root", root, "--query", "How do I install the SDK?", "--policy", policy)
    assert result.returncode != 0
    assert '"decision": "answered"' not in result.stdout


def test_hook_rejects_explicit_missing_policy(tmp_path):
    event = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "README.md"}})
    result = run_script(HOOK, input_text=event,
                        env={"AUTO_SUPPORT_POLICY": str(tmp_path / "missing.json")})
    assert result.returncode == 2


def test_init_resolved_product_passes_doctor_without_hidden_files(tmp_path):
    companion = tmp_path / "synthetic-companion"
    result = run_script(SCRIPTS / "init_config.py", "--slug", "example", "--out", companion)
    assert result.returncode == 0, result.stderr
    product_path = companion / "products/example/product.json"
    product = json.loads(product_path.read_text(encoding="utf-8"))
    product["product_root"] = str(tmp_path / "synthetic-public-docs")
    Path(product["product_root"]).mkdir()
    product_path.write_text(json.dumps(product), encoding="utf-8")
    result = run_script(SCRIPTS / "verify_config.py", "--config-dir", companion)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_product_manifest_cannot_pass_doctor(tmp_path):
    companion = tmp_path / "synthetic-companion"
    assert run_script(SCRIPTS / "init_config.py", "--out", companion).returncode == 0
    (companion / "products/example/product.json").unlink()
    result = run_script(SCRIPTS / "verify_config.py", "--config-dir", companion)
    assert result.returncode == 1
    assert "product.json" in result.stdout


def test_init_rejects_product_path_escape_without_writing(tmp_path):
    companion = tmp_path / "synthetic-companion"
    result = run_script(SCRIPTS / "init_config.py", "--slug", "../../escaped", "--out", companion)
    assert result.returncode != 0
    assert not companion.exists()
    assert not (tmp_path / "escaped").exists()
