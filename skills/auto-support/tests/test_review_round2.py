"""Structured-answer and persistence regressions using synthetic receipts."""
import copy
import json
from types import SimpleNamespace

import pytest

import answer_pipeline as AP
import egress_dlp as E
import grounding as GR
import reminder_bridge as RB
import runtime_data as D


@pytest.fixture(autouse=True)
def private_receipt_fixture(tmp_path, monkeypatch):
    """Receipt tests use synthetic PRIVATE proof before their transport callbacks."""
    root = tmp_path / "synthetic-companion"
    root.mkdir()
    monkeypatch.setenv("SCHEDULE_DB_PATH", str(root / "support.db"))
    def command(argv, **kwargs):
        if argv[0] == "gh":
            return "true"
        if "rev-parse" in argv:
            return str(root)
        if argv[3:] == ["remote"]:
            return "origin"
        if "--get-regexp" in argv:
            return ""
        if argv[3:] == ["config", "--null", "--list"]:
            return ""
        if argv[3:5] == ["remote", "get-url"]:
            return "https://github.com/example-owner/example-config.git"
        pytest.fail("unexpected private-boundary command")
    monkeypatch.setattr(D, "_run", command)


def answer():
    return {
        "response_text": "The timeout is 2.5 seconds. [docs/limits.md:7]",
        "needs_escalation": False,
        "cited_sources": ["docs/limits.md:7"],
        "cited_internal_paths": [],
        "contains_secret": False,
    }


@pytest.mark.parametrize("field", list(answer()))
def test_every_answer_field_is_required(field):
    candidate = answer()
    del candidate[field]
    assert not E.evaluate(candidate, require_citation=False).allowed


@pytest.mark.parametrize("field,value", [
    ("needs_escalation", None), ("needs_escalation", 0),
    ("contains_secret", None), ("contains_secret", 0),
    ("contains_secret", ""), ("contains_secret", []),
    ("cited_internal_paths", None), ("cited_internal_paths", False),
    ("cited_internal_paths", 0), ("cited_internal_paths", ""),
    ("cited_internal_paths", {}),
])
def test_falsey_wrong_schema_types_are_rejected(field, value):
    candidate = answer()
    candidate[field] = value
    assert not E.evaluate(candidate).allowed


@pytest.mark.parametrize("escalate", [False, True])
def test_valid_answer_schema_and_escalation_control(escalate):
    candidate = answer()
    candidate["needs_escalation"] = escalate
    result = E.evaluate(candidate)
    assert result.allowed and result.escalate is escalate


def test_pipeline_reports_only_citations_used_in_the_answer(monkeypatch):
    snippets = [GR.Snippet("docs/limits.md", 7, "The timeout is 2.5 seconds."),
                GR.Snippet("docs/retries.md", 9, "The retry timeout is 4 seconds.")]
    monkeypatch.setattr(AP.R, "search", lambda *args: snippets)
    result = AP.handle("what is the timeout?", ".", ["docs/**"], [],
                       generate=lambda *args: answer())
    assert result.decision == "answered"
    assert result.citations == ["docs/limits.md:7"]


def receipt(state="pending", iid="synthetic-ticket"):
    return {"api_version": "1.0.0", "schema_version": 1, "ok": True,
            "item": {"id": iid, "state": state, "kind": "task"}}


@pytest.mark.parametrize("payload", [
    {}, [], None, {"ok": False},
    {**receipt(), "ok": 1}, {**receipt(), "api_version": "2.0.0"},
    {**receipt(), "api_version": None}, {**receipt(), "schema_version": True},
    {**receipt(), "item": {}}, {**receipt(), "item": None},
    receipt(iid=""), receipt(iid=1), receipt(state=None), receipt(state="invented"),
])
def test_malformed_success_receipt_cannot_report_persistence(monkeypatch, payload):
    monkeypatch.setattr(RB.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""))
    with pytest.raises(RB.ReminderError):
        RB.record_turn("msg-1", channel="c", user_id="u", intent="unclear",
                       decision="abstain", question="synthetic question")


@pytest.mark.parametrize("stdout", ["", "not json", "log line\n" + json.dumps(receipt())])
def test_noncontract_stdout_is_rejected(monkeypatch, stdout):
    monkeypatch.setattr(RB.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout=stdout, stderr=""))
    with pytest.raises(RB.ReminderError):
        RB._call("add", [])


@pytest.mark.parametrize("payload", [receipt("pending"), receipt("doing", "other-ticket")])
def test_transition_receipt_must_confirm_requested_state_and_id(monkeypatch, payload):
    replies = iter([receipt(), payload])
    monkeypatch.setattr(RB.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout=json.dumps(next(replies)), stderr=""))
    with pytest.raises(RB.ReminderError):
        RB.record_turn("msg-1", channel="c", user_id="u", intent="unclear",
                       decision="doing", question="synthetic question")


@pytest.mark.parametrize("decision,target", [
    ("answered", "done"), ("doing", "doing"), ("abstain", "pending"),
    ("escalate", "blocked"), ("blocked-leak", "blocked"), ("cancelled", "cancelled"),
])
def test_replay_preserves_state_and_does_not_repeat_transitions(monkeypatch, decision, target):
    current = receipt()
    transitions = []

    def run(argv, **kwargs):
        verb = argv[argv.index("--actor") + 2]
        if verb != "add":
            transitions.append(verb)
            old = current["item"]["state"]
            if old in ("done", "cancelled"):
                return SimpleNamespace(returncode=1, stdout="", stderr=json.dumps({
                    "error_code": "ERR_ILLEGAL_TRANSITION", "message": "protected terminal"}))
            if verb == "transition":
                new = argv[argv.index("--to") + 1]
            else:
                new = {"done": "done", "block": "blocked"}[verb]
            current["item"]["state"] = new
        return SimpleNamespace(returncode=0, stdout=json.dumps(current), stderr="")

    monkeypatch.setattr(RB.subprocess, "run", run)
    args = dict(channel="c", user_id="u", intent="unclear", decision=decision,
                question="synthetic question")
    first = RB.record_turn("msg-1", **args)
    before_replay = copy.copy(transitions)
    second = RB.record_turn("msg-1", **args)
    assert first["id"] == second["id"]
    assert second["state"] == target
    assert transitions == before_replay


@pytest.mark.parametrize("state", ["done", "cancelled"])
def test_replayed_turn_never_reopens_terminal_item(monkeypatch, state):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv[argv.index("--actor") + 2])
        return SimpleNamespace(returncode=0, stdout=json.dumps(receipt(state)), stderr="")

    monkeypatch.setattr(RB.subprocess, "run", run)
    result = RB.record_turn("msg-1", channel="c", user_id="u", intent="unclear",
                            decision="escalate", question="synthetic question")
    assert result["state"] == state and calls == ["add"]
