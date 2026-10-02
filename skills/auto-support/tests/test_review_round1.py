"""Independent-review regressions with synthetic inputs and intercepted delivery."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import answer_pipeline as A
import grounding as GR
import guardrails as G
import escalate as E
import reminder_bridge as RB
import pretooluse_hook as H
from test_first_run_contract import run_script, SCRIPTS, PIPELINE, HOOK


@pytest.mark.parametrize("tool, inputs", [
    ("Read", {"file_path": "C:/synthetic-private/secrets/README.md"}),
    ("Bash", {"command": "cat C:/synthetic-private/secrets/README.md"}),
    ("Grep", {"pattern": "README.md"}),
    ("Glob", {"pattern": "README.md"}),
])
def test_hook_rejects_outside_or_unbounded_targets(tool, inputs):
    assert run_script(HOOK, input_text=json.dumps({"tool_name": tool, "tool_input": inputs})).returncode == 2


@pytest.mark.parametrize("replacement", [
    "The timeout is 2.5 milliseconds [docs/limits.md:7].",
    "The timeout is 2.5 seconds and encryption is disabled [docs/limits.md:7].",
])
def test_generator_must_not_invent_units_or_extra_facts(monkeypatch, replacement):
    source = GR.Snippet("docs/limits.md", 7, "The timeout is 2.5 seconds.")
    monkeypatch.setattr(A.R, "search", lambda *a: [source])
    def generate(*args):
        ans = A._default_generate("timeout", [source])
        ans["response_text"] = replacement
        return ans
    assert A.handle("what is the timeout?", ".", ["docs/**"], ["secrets/**"], generate=generate).decision != "answered"


@pytest.mark.parametrize("mutation", ["fabricated_citation", "escalate", "wrong_bool"])
def test_generation_metadata_is_honored_and_evidence_bound(monkeypatch, mutation):
    source = GR.Snippet("docs/limits.md", 7, "The timeout is 2.5 seconds.")
    monkeypatch.setattr(A.R, "search", lambda *a: [source])
    def generate(*args):
        ans = A._default_generate("timeout", [source])
        if mutation == "fabricated_citation":
            ans["cited_sources"].append("docs/missing.md:1")
        elif mutation == "escalate":
            ans["needs_escalation"] = True
        else:
            ans["needs_escalation"] = "false"
        return ans
    assert A.handle("what is the timeout?", ".", ["docs/**"], ["secrets/**"], generate=generate).decision != "answered"


def test_secret_sanitization_covers_question_and_metadata():
    secret = 'api_key="' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4' + '"'
    assert G.scan_secrets(secret).hit
    assert secret not in E._redact(secret)
    payload = RB._ext(secret, secret, secret, "product_usage_question", "escalate", answer_ref=secret, question=secret)
    assert "A1b2C3d4E5f6G7h8I9j0K1l2M3n4" not in payload


@pytest.mark.parametrize("receipt", [
    {}, {"sent": False, "dry_run": True}, {"sent": True, "dry_run": True},
    {"sent": True}, {"sent": "true", "dry_run": False},
])
def test_zero_exit_without_delivery_receipt_does_not_start_cooldown(tmp_path, monkeypatch, receipt):
    state = tmp_path / "synthetic-state.json"
    monkeypatch.setattr(E, "_state_path", lambda value: state)
    monkeypatch.setattr(E.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(receipt)))
    result = E.escalate("synthetic question", trigger="low_confidence", relay_cmd="synthetic-relay.py", now=20000)
    assert not result.sent and not state.exists()


def test_null_registry_is_not_draft_ready(tmp_path):
    cfg = tmp_path / "synthetic-companion"
    assert run_script(SCRIPTS / "init_config.py", "--out", cfg).returncode == 0
    product_path = cfg / "products/example/product.json"
    product = json.loads(product_path.read_text())
    product["product_root"] = str(tmp_path)
    product_path.write_text(json.dumps(product))
    (cfg / "registry.json").write_text("null")
    assert run_script(SCRIPTS / "verify_config.py", "--config-dir", cfg).returncode == 1


def test_direct_public_docs_root_works_without_readme(tmp_path):
    cfg = tmp_path / "synthetic-companion"
    assert run_script(SCRIPTS / "init_config.py", "--out", cfg).returncode == 0
    docs = tmp_path / "public-docs"
    docs.mkdir()
    (docs / "usage.md").write_text("Install the synthetic SDK using the public installer.")
    product_path = cfg / "products/example/product.json"
    product = json.loads(product_path.read_text());product["product_root"] = str(docs)
    product_path.write_text(json.dumps(product))
    result = run_script(PIPELINE, "--policy", product_path.with_name("policy.json"), "--query", "How do I install the SDK?")
    assert result.returncode == 0
    answer = json.loads(result.stdout)
    assert answer["decision"] == "answered" and "usage.md:1" in answer["response_text"]


def test_configured_hook_allows_public_reads_and_searches_only(tmp_path):
    cfg = tmp_path / "synthetic-companion"
    assert run_script(SCRIPTS / "init_config.py", "--out", cfg).returncode == 0
    docs = tmp_path / "public-docs"
    docs.mkdir()
    (docs / "usage.md").write_text("Install the synthetic SDK.")
    product_path = cfg / "products/example/product.json"
    product = json.loads(product_path.read_text())
    product["product_root"] = str(docs)
    product_path.write_text(json.dumps(product))
    env = {"AUTO_SUPPORT_POLICY": str(product_path.with_name("policy.json"))}
    for tool, inputs in [
        ("Read", {"file_path": "usage.md"}),
        ("Bash", {"command": "cat usage.md"}),
        ("Grep", {"pattern": "SDK", "path": "."}),
        ("Glob", {"pattern": "*.md", "path": "."}),
    ]:
        event = {"tool_name": tool, "tool_input": inputs, "cwd": str(docs)}
        result = run_script(HOOK, input_text=json.dumps(event), env=env)
        assert result.returncode == 0, result.stderr
    private = docs / "secrets"
    private.mkdir()
    (private / "record.md").write_text("synthetic private record")
    for tool in ("Grep", "Glob"):
        event = {"tool_name": tool, "tool_input": {"path": ".", "pattern": "*.md"}, "cwd": str(docs)}
        assert run_script(HOOK, input_text=json.dumps(event), env=env).returncode == 2


def test_search_rejects_directory_alias_outside_root(tmp_path, monkeypatch):
    root = tmp_path / "public"
    root.mkdir()
    alias = root / "docs"
    alias.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    resolve = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda p, *a, **kw: outside if p == alias else resolve(p, *a, **kw))
    assert not H._search_target("docs", root, root, ["docs/**"], ["secrets/**"])


def test_valid_delivery_receipt_starts_cooldown_and_redacts_all_fields(tmp_path, monkeypatch):
    state = tmp_path / "synthetic-state.json"
    secret = 'api_key="' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4' + '"'
    calls = []
    monkeypatch.setattr(E, "_state_path", lambda value: state)
    def send(argv, **kwargs):
        calls.append(argv)
        assert "A1b2C3d4E5f6G7h8I9j0K1l2M3n4" not in argv[-1]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"sent": True, "dry_run": False}))
    monkeypatch.setattr(E.subprocess, "run", send)
    args = dict(trigger="low_confidence", user_id=secret, channel=secret,
                answer_ref=secret, relay_cmd="synthetic-relay.py")
    result = E.escalate(secret, now=20000, **args)
    assert result.sent and state.exists()
    assert E.escalate(secret, now=20001, **args).suppressed
    assert len(calls) == 1 and secret not in state.read_text()


def test_reminder_rejects_sensitive_id_before_persistence(monkeypatch):
    monkeypatch.setattr(RB, "_call", lambda *a, **kw: pytest.fail("unexpected persistence"))
    with pytest.raises(RB.ReminderError, match="message_id"):
        RB.record_turn("user1@example.com", channel="synthetic", user_id="synthetic",
                       intent="unclear", decision="escalate", question="synthetic")


def test_reminder_redacts_transition_reason(monkeypatch):
    calls = []
    def call(verb, args, db):
        calls.append((verb, args))
        return {"item": {"id": "synthetic-ticket", "state": "pending" if verb == "add" else "blocked"}}
    monkeypatch.setattr(RB, "_call", call)
    RB.record_turn("msg-1", channel="synthetic", user_id="synthetic", intent="unclear",
                   decision="escalate", question="synthetic", trigger="user1@example.com")
    assert len(calls) == 2 and "user1@example.com" not in json.dumps(calls)
