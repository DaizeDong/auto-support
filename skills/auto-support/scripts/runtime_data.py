"""Resolve escalation output inside the separate PRIVATE companion.

Discovery is provided by the installed fleet_guards package. This adapter adds path-only target
containment: the destination must be inside a Git worktree outside this tool tree.
An unresolved companion is an error before any write or send; there is no in-repo
fallback. Repository visibility is enforced at commit time, not at runtime.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat

REPO_ROOT = Path(__file__).resolve().parents[3]


class DataBoundaryError(RuntimeError):
    pass


def _guard_base(*, companion=False, override=None, required=True):
    if override is not None:
        selected = Path(override).expanduser()
        if not str(override).strip() or not selected.is_dir():
            raise DataBoundaryError("Explicit config directory must exist")
        return selected.resolve() if companion else (selected / "data" if (selected / "data").is_dir() else selected).resolve()
    for name in ("AUTO_SUPPORT_DATA_DIR", "AUTO_SUPPORT_CONFIG"):
        value = os.environ.get(name)
        if value:
            if not Path(value).expanduser().is_dir():
                raise DataBoundaryError(name + " must name an existing private directory")
            break
    try:
        from fleet_guards.runtime import companion_resolver
    except ImportError as exc:
        raise DataBoundaryError('fleet_guards is not installed; run: pip install -e "$(git config --get fleet.guards)"') from exc
    resolver = companion_resolver(source_root=REPO_ROOT)
    try:
        result = (resolver.resolve_companion_root("auto-support") if companion else
                  resolver.resolve_data_dir("auto-support", create=False))
    except (OSError, ValueError, RuntimeError) as exc:
        raise DataBoundaryError("Cannot resolve the private companion; check AUTO_SUPPORT_CONFIG") from exc
    if result is None and not required:
        return None
    if result is None:
        raise DataBoundaryError("Set AUTO_SUPPORT_CONFIG to a PRIVATE versioned companion before recording escalations")
    return Path(result).resolve()


def _private_repo(path):
    """Return the Git worktree that will version ``path``; filesystem checks only.

    No process starts and repository visibility is not checked at runtime: commit-time
    hooks enforce PRIVATE publication. The destination must sit inside a Git
    worktree (the companion) that is neither this public tool tree nor one containing it.
    """
    path = Path(path).absolute()
    for node in (path, *path.parents):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise DataBoundaryError("Runtime output cannot use filesystem aliases")
    existing = path
    while not existing.is_dir() and existing != existing.parent:
        existing = existing.parent
    root = next((directory for directory in (existing, *existing.parents)
                 if os.path.lexists(directory / ".git")), None)
    if root is None:
        raise DataBoundaryError("Runtime output requires a PRIVATE versioned companion (no Git worktree found)")
    root = root.resolve()
    if root.is_relative_to(REPO_ROOT) or REPO_ROOT.is_relative_to(root):
        raise DataBoundaryError("Escalation data cannot reside in the tool repository")
    return root


def private_file_path(value, *, sidecars=()):
    """Validate a selected runtime file and its sidecars without creating anything.

    Every existing destination must stay in the same companion worktree.
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
    target = requested.resolve()
    for path in [target, *(Path(str(target) + suffix) for suffix in sidecars)]:
        actual = path.resolve()
        safe_components(actual)
        if actual == root or not actual.is_relative_to(root) or actual.is_dir():
            raise DataBoundaryError("Runtime destination must remain a file in the selected private repository")
        if actual.exists() and actual.stat().st_nlink > 1:
            raise DataBoundaryError("Runtime destination cannot be a hard link")
        if _private_repo(actual) != root:
            raise DataBoundaryError("Runtime destination crosses a repository boundary")
    return target


def state_path(value=None):
    base = _guard_base()
    if base.is_relative_to(REPO_ROOT):
        raise DataBoundaryError("Output cannot be inside the public tool repository")
    if value is None:
        value = "escalation_state.json"
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
    return private_file_path(target, sidecars=(".lock", ".tmp"))
