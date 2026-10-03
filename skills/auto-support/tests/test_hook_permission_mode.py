"""Host permission metadata must preserve the support deployment contract."""
import json
import os
from fnmatch import fnmatchcase
from pathlib import Path
import subprocess
import sys

import pytest

from test_first_run_contract import HOOK
from test_review_acceptance_a import fixtures


@pytest.mark.parametrize("case", fixtures.hook_permission_mode_cases(), ids=lambda case: case["id"])
def test_hook_requires_supported_non_bypass_permission_mode(tmp_path, case):
    event = fixtures.hook_event("Read", {"file_path": str(tmp_path / "README.md")},
                               cwd=str(tmp_path))
    event.pop("permission_mode")
    event.update(case["fields"])
    env = {key: value for key, value in os.environ.items() if not key.startswith("AUTO_SUPPORT_")}
    result = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(event),
                            capture_output=True, text=True, encoding="utf-8", cwd=tmp_path,
                            env=env, timeout=20)
    assert result.returncode == (0 if case["allowed"] else 2), result.stderr
    if not case["allowed"]:
        assert "permission mode" in result.stderr


def _mcp_host_decision(permissions, tool, inherited_deny):
    """Model only documented MCP deny/ask/allow precedence, not native host dispatch."""
    for decision in ("deny", "ask", "allow"):
        rules = permissions.get(decision, [])
        if decision == "deny":
            rules = [*rules, *inherited_deny]
        if any(fnmatchcase(tool, rule) for rule in rules if rule.startswith("mcp__")):
            return decision
    return "ask"


@pytest.mark.parametrize("case", fixtures.hook_relay_permission_cases(), ids=lambda case: case["id"])
def test_template_relay_requires_normal_prompt_and_exact_hook_admission(tmp_path, case):
    template = Path(__file__).resolve().parents[1] / "templates/settings.json.template"
    permissions = json.loads(template.read_text(encoding="utf-8"))["permissions"]
    event = fixtures.hook_event(case["tool"], {}, cwd=str(tmp_path),
                               permission_mode=permissions.get("defaultMode", "default"))
    env = {key: value for key, value in os.environ.items() if not key.startswith("AUTO_SUPPORT_")}
    env["AUTO_SUPPORT_MCP_ALLOW"] = case["hook_allow"]
    hook = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(event),
                          capture_output=True, text=True, encoding="utf-8", cwd=tmp_path,
                          env=env, timeout=20)
    host_decision = _mcp_host_decision(permissions, case["tool"], case["inherited_deny"])
    assert host_decision == case["host_decision"]
    assert hook.returncode == case["hook_returncode"], hook.stderr
    # An inert recorder stands in for the relay. No transport is imported or invoked.
    delivered = []
    if hook.returncode == 0 and (host_decision == "allow" or
                                host_decision == "ask" and case["prompt_approved"]):
        delivered.append(case["tool"])
    assert delivered == ([case["tool"]] if case["dispatched"] else [])
