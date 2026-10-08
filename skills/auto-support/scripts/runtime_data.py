"""Verify escalation output belongs to a separate PRIVATE GitHub companion.

Discovery is provided by the pinned guards kit. This adapter adds live visibility
proof and target containment; missing proof is an error before any write or send.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

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


def _guard_base(*, companion=False, override=None, required=True):
    path = REPO_ROOT / "guards/tools/datadir.py"
    if not path.is_file():
        raise DataBoundaryError("Missing guards kit; run git submodule update --init --recursive")
    if override is not None:
        selected = Path(override).expanduser()
        if not str(override).strip() or not selected.is_dir():
            raise DataBoundaryError("Explicit config directory must exist")
        return selected.resolve() if companion else (selected / "data" if (selected / "data").is_dir() else selected).resolve()
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
        result = (module.resolve_companion_root("auto-support") if companion else
                  module.resolve_data_dir("auto-support", create=False))
    except (OSError, ValueError, RuntimeError) as exc:
        raise DataBoundaryError("Cannot resolve the private companion; check AUTO_SUPPORT_CONFIG") from exc
    if result is None and not required:
        return None
    if result is None:
        raise DataBoundaryError("Set AUTO_SUPPORT_CONFIG to a PRIVATE versioned companion before recording escalations")
    return Path(result).resolve()


def _boundary_module():
    """Load only the selected kit's supported companion-proof API."""
    path = REPO_ROOT / "guards/tools/data_boundary.py"
    try:
        for node in (path, *path.parents):
            info = node.lstat()
            if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                    or stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
                raise DataBoundaryError("Guards dependency has an unproved filesystem alias")
        spec = importlib.util.spec_from_file_location("_auto_support_companion_boundary", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not all(callable(getattr(module, name, None)) for name in
                   ("prove_private_companion", "read_private_companion_git")):
            raise DataBoundaryError("Guards dependency lacks the supported companion-proof API")
        return module
    except (OSError, ValueError, ImportError, AttributeError, RuntimeError, TypeError) as exc:
        raise DataBoundaryError("Cannot load companion proof; initialize the accepted guards kit") from exc


def _verify_visibility_environment():
    """The live gh query must use the standard HTTPS endpoint and trust settings."""
    overrides = {"http_proxy", "https_proxy", "all_proxy", "curl_ca_bundle",
                 "ssl_cert_file", "ssl_cert_dir"}
    if any(name.casefold() in overrides for name in os.environ):
        raise DataBoundaryError("Live visibility HTTPS transport has an unproved environment override")


def _private_repo(path):
    # Preserve the consumer's explicit refusal of ambient repository selectors.
    administrative = {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_CONFIG",
                      "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"}
    if any(name.upper() in administrative or name.upper().startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
           for name in os.environ):
        raise DataBoundaryError("Clear Git administrative and command-config overrides before selecting private output")
    existing = path
    while not existing.is_dir() and existing != existing.parent:
        existing = existing.parent
    try:
        boundary = _boundary_module()
        proof = boundary.prove_private_companion(existing)
        root = Path(proof.root).resolve()
        if root.is_relative_to(REPO_ROOT) or REPO_ROOT.is_relative_to(root):
            raise DataBoundaryError("Escalation data cannot reside in the tool repository")
        if not path.resolve().is_relative_to(root):
            raise DataBoundaryError("PRIVATE repository does not govern the selected output")
        head = boundary.read_private_companion_git(proof, "rev-parse", "--verify", "HEAD")
        if head.returncode != 0 or not head.stdout.strip():
            raise DataBoundaryError("PRIVATE companion has no committed history")
        relative = path.resolve().relative_to(root).as_posix()
        ignored = boundary.read_private_companion_git(
            proof, "check-ignore", "--no-index", "-q", "--", relative)
        if ignored.returncode != 1:
            raise DataBoundaryError("Runtime output is ignored or its version-control eligibility is unknown")
        _verify_visibility_environment()
        for repository in proof.repositories:
            if _run(["gh", "api", "--hostname", "github.com", "repos/" + repository,
                     "--jq", ".private"]) != "true":
                raise DataBoundaryError("Companion is PUBLIC or live visibility is unknown")
        current = boundary.prove_private_companion(existing)
        if (current.root, current.repositories, current.signature) != (
                proof.root, proof.repositories, proof.signature):
            raise DataBoundaryError("Companion publication state changed during live visibility proof")
        return root
    except (OSError, ValueError, RuntimeError, TypeError, AttributeError) as exc:
        raise DataBoundaryError("Cannot prove PRIVATE output: " + str(exc)) from exc


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
    root = _private_repo(requested)
    verified_paths = {requested.resolve(): root}
    target = requested.resolve()
    for path in [target, *(Path(str(target) + suffix) for suffix in sidecars)]:
        actual = path.resolve()
        safe_components(actual)
        if actual == root or not actual.is_relative_to(root) or actual.is_dir():
            raise DataBoundaryError("Runtime destination must remain a file in the selected private repository")
        if actual.exists() and actual.stat().st_nlink > 1:
            raise DataBoundaryError("Runtime destination cannot be a hard link")
        if actual not in verified_paths:
            verified_paths[actual] = _private_repo(actual)
        if verified_paths[actual] != root:
            raise DataBoundaryError("Runtime destination crosses a repository boundary")
    return target


def _storage_api():
    path = REPO_ROOT / 'guards/tools/storage_contract.py'
    spec = importlib.util.spec_from_file_location('_auto_support_storage', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _authorize_state(target, root):
    try:
        module = _storage_api()
        for candidate in (target, Path(str(target) + '.lock'), Path(str(target) + '.tmp')):
            module.authorize_artifact_write(REPO_ROOT, root, candidate.relative_to(root).as_posix())
    except (OSError, ValueError, RuntimeError, AttributeError) as exc:
        raise DataBoundaryError('Escalation output requires a source-owned versioned artifact declaration') from exc


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
    if _private_repo(target) != root:
        raise DataBoundaryError("State destination crosses a repository boundary")
    target = private_file_path(target, sidecars=(".lock", ".tmp"))
    _authorize_state(target, root)
    return target
