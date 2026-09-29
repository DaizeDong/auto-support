"""Verify escalation output belongs to a separate PRIVATE GitHub companion.

Discovery is provided by the pinned guards kit. This adapter adds live visibility
proof and target containment; missing proof is an error before any write or send.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[3]


class DataBoundaryError(RuntimeError):
    pass


def _run(argv, *, empty_ok=False):
    try:
        environment = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=20,
                                env=environment)
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired) as exc:
        raise DataBoundaryError("Cannot verify private output: command unavailable or failed") from exc
    if empty_ok and result.returncode == 1 and not result.stdout and not result.stderr:
        return ""
    if result.returncode:
        raise DataBoundaryError("Cannot verify private output: command returned an error")
    return result.stdout.strip()


def _guard_base():
    path = REPO_ROOT / "guards/tools/datadir.py"
    if not path.is_file():
        raise DataBoundaryError("Missing guards kit; run git submodule update --init --recursive")
    for name in ("AUTO_SUPPORT_DATA_DIR", "AUTO_SUPPORT_CONFIG", "AUTO_SUPPORT_CONFIG_DIR"):
        value = os.environ.get(name)
        if value:
            if not Path(value).expanduser().is_dir():
                raise DataBoundaryError(name + " must name an existing private directory")
            break
    spec = importlib.util.spec_from_file_location("_auto_support_datadir", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        result = module.resolve_data_dir("auto-support", create=False)
    except (OSError, ValueError, RuntimeError) as exc:
        raise DataBoundaryError("Cannot resolve the private companion; check AUTO_SUPPORT_CONFIG") from exc
    if result is None:
        raise DataBoundaryError("Set AUTO_SUPPORT_CONFIG to a PRIVATE versioned companion before recording escalations")
    return Path(result).resolve()


def _prove_private_destination(remote):
    """Prove one Git-resolved destination, never an unexpanded config URL."""
    if "://" in remote:
        parsed = urlsplit(remote)
        if parsed.scheme not in ("ssh", "https") or parsed.password or parsed.query or parsed.fragment:
            raise DataBoundaryError("Unsupported companion origin")
        host, name = parsed.hostname, parsed.path.lstrip("/")
        ssh = parsed.scheme == "ssh"
    else:
        match = re.fullmatch(r"(?:[^@/:\s]+@)?([^/:\s]+):([^\s]+)", remote)
        if not match:
            raise DataBoundaryError("Missing supported GitHub companion origin")
        host, name = match.groups()
        ssh = True
    if host != "github.com":
        if not ssh or not re.fullmatch(r"[a-zA-Z0-9_.-]+", host or ""):
            raise DataBoundaryError("Cannot prove non-GitHub companion visibility")
        config = _run(["ssh", "-G", host])
        hosts = [line.split(None, 1)[1].strip() for line in config.splitlines() if line.startswith("hostname ")]
        if hosts != ["github.com"]:
            raise DataBoundaryError("SSH alias does not resolve to GitHub")
    name = name.removesuffix(".git")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", name):
        raise DataBoundaryError("Invalid companion repository identity")
    if _run(["gh", "api", "--hostname", "github.com", "repos/" + name, "--jq", ".private"]) != "true":
        raise DataBoundaryError("Companion is PUBLIC or visibility is unknown")


def _private_repo(path):
    existing = path
    while not existing.is_dir() and existing != existing.parent:
        existing = existing.parent
    root = Path(_run(["git", "-C", str(existing), "rev-parse", "--show-toplevel"])).resolve()
    if root.is_relative_to(REPO_ROOT) or REPO_ROOT.is_relative_to(root):
        raise DataBoundaryError("Escalation data cannot reside in the tool repository")
    git = ["git", "-C", str(root)]
    remotes = set(_run([*git, "remote"]).splitlines())
    if "origin" not in remotes:
        raise DataBoundaryError("Missing supported GitHub companion origin")
    # Check every configured remote, so changing the current branch or default push
    # selection cannot select an unchecked publisher. Unknown selections fail closed.
    selections = _run([*git, "config", "--null", "--get-regexp",
                       r"^(remote\.pushdefault|branch\..*\.(pushremote|remote))$"], empty_ok=True)
    for entry in selections.split("\0"):
        if not entry:
            continue
        key, separator, remote = entry.partition("\n")
        if not separator or not key or remote not in remotes:
            raise DataBoundaryError("Companion push selection is not a verified named remote")
    destinations = set()
    for remote in sorted(remotes):
        for direction in ([], ["--push"]):
            # Git expands insteadOf/pushInsteadOf and reports every URL, including
            # multiple pushurl entries. Reading remote.origin.url cannot do this.
            urls = _run([*git, "remote", "get-url", *direction, "--all", remote]).splitlines()
            if not urls or any(not url.strip() for url in urls):
                raise DataBoundaryError("Missing companion publication destination")
            destinations.update(urls)
    for destination in sorted(destinations):
        _prove_private_destination(destination)
    return root


def private_file_path(value, *, sidecars=()):
    """Validate a selected runtime file and its sidecars without creating anything.

    Every existing destination must stay in the same verified private repository.
    SQLite sidecars and hard links cannot redirect writes outside that boundary.
    """
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise DataBoundaryError("Select an absolute runtime file in a PRIVATE versioned companion")
    requested = Path(value).expanduser()
    if not requested.is_absolute():
        raise DataBoundaryError("Runtime output must be an absolute path")

    def safe_components(path):
        for part in path.parts[1:]:
            stem = part.split(".", 1)[0].upper()
            if (part.lower() in ("..", ".git") or part.endswith((" ", ".")) or ":" in part
                    or stem in {"CON", "PRN", "AUX", "NUL"}
                    or re.fullmatch(r"(?:COM|LPT)[1-9]", stem)):
                raise DataBoundaryError("Runtime path contains unsafe components")

    safe_components(requested)
    root = _private_repo(requested.parent)
    verified_parents = {requested.parent.resolve(): root}
    target = requested.resolve()
    for path in [target, *(Path(str(target) + suffix) for suffix in sidecars)]:
        actual = path.resolve()
        safe_components(actual)
        if actual == root or not actual.is_relative_to(root) or actual.is_dir():
            raise DataBoundaryError("Runtime destination must remain a file in the selected private repository")
        if actual.exists() and actual.stat().st_nlink > 1:
            raise DataBoundaryError("Runtime destination cannot be a hard link")
        parent = actual.parent
        if parent not in verified_parents:
            verified_parents[parent] = _private_repo(parent)
        if verified_parents[parent] != root:
            raise DataBoundaryError("Runtime destination crosses a repository boundary")
    return target


def state_path(value=None):
    base = _guard_base()
    if base.is_relative_to(REPO_ROOT):
        raise DataBoundaryError("Output cannot be inside the public tool repository")
    if value is None:
        legacy = os.environ.get("AUTO_SUPPORT_STATE_DIR")
        value = Path(legacy) / "escalation_state.json" if legacy else "escalation_state.json"
    raw = str(value).replace("\\", "/")
    if any(part.lower() in ("..", ".git") or part.endswith((" ", ".")) for part in raw.split("/")):
        raise DataBoundaryError("State path contains unsafe components")
    requested = Path(value).expanduser()
    if requested.drive and not requested.is_absolute():
        raise DataBoundaryError("Drive-relative output is not allowed")
    target = (requested if requested.is_absolute() else base / requested).resolve()
    if not target.is_relative_to(base) or target == base or ":" in str(target.relative_to(base)):
        raise DataBoundaryError("State path must remain inside the private data directory")
    root = _private_repo(base)
    if _private_repo(target.parent) != root:
        raise DataBoundaryError("State destination crosses a repository boundary")
    return target
