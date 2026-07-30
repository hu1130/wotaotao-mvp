"""Canonical employee names and tenant-scoped filesystem paths."""

from __future__ import annotations

import re
from pathlib import Path

from core.tenant import normalize_tenant_id


MAX_EMPLOYEE_NAME_LENGTH = 120
_INVALID_PATH_CHARS = set('<>:"/\\|?*\x00')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def normalize_employee_name(value: str) -> str:
    """Return a cross-platform-safe display name or raise ``ValueError``."""

    name = str(value or "").strip()
    if not name:
        raise ValueError("name is required")
    if len(name) > MAX_EMPLOYEE_NAME_LENGTH:
        raise ValueError(
            f"name is too long; maximum is {MAX_EMPLOYEE_NAME_LENGTH} characters"
        )
    if name in {".", ".."}:
        raise ValueError("name cannot be '.' or '..'")
    if any(char in _INVALID_PATH_CHARS for char in name) or _CONTROL_CHAR_RE.search(name):
        raise ValueError("name contains invalid path characters")
    if name.endswith((".", " ")):
        raise ValueError("name cannot end with a dot or space")
    if name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ValueError("name is reserved by Windows")
    return name


def tenant_employee_directory(
    root: str | Path,
    tenant_id: str,
    employee_name: str,
) -> Path:
    """Build a resolved employee directory that cannot escape its tenant root."""

    root_path = Path(root).expanduser().resolve()
    tenant_root = (root_path / normalize_tenant_id(tenant_id)).resolve()
    name = normalize_employee_name(employee_name)
    target = (tenant_root / name).resolve()
    if target.parent != tenant_root:
        raise ValueError("employee directory escaped tenant root")
    return target


def require_path_inside_tenant_roots(
    path: str | Path,
    *,
    tenant_id: str,
    roots: list[str | Path],
) -> Path:
    """Resolve a path and require it to be inside one of the tenant subdirectories."""

    resolved = Path(path).expanduser().resolve()
    tenant = normalize_tenant_id(tenant_id)
    tenant_roots = [(Path(root).expanduser().resolve() / tenant).resolve() for root in roots]
    if not any(resolved == root or resolved.is_relative_to(root) for root in tenant_roots):
        allowed = ", ".join(str(root) for root in tenant_roots)
        raise ValueError(
            f"path must be inside current tenant directories, got {resolved}; allowed: {allowed}"
        )
    return resolved
