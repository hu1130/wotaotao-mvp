"""Validate shared-runtime ownership and explicit role overrides."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = REPO_ROOT / "shared_runtime"
SERVER_ROOT = REPO_ROOT / "server_deploy"
CLIENT_ROOT = REPO_ROOT / "client_deploy"
OVERRIDES_PATH = SHARED_ROOT / "role_overrides.json"
PACKAGE_ADAPTERS = {
    "config/__init__.py",
    "core/__init__.py",
    "core/knowledge/__init__.py",
    "core/speech_streaming/__init__.py",
}


def relative_files(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for domain in ("config", "core"):
        domain_root = root / domain
        if not domain_root.exists():
            continue
        for path in domain_root.rglob("*"):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or "data" in path.relative_to(domain_root).parts
            ):
                continue
            result[path.relative_to(root).as_posix()] = path
    return result


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> int:
    overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    shared = relative_files(SHARED_ROOT)
    server = relative_files(SERVER_ROOT)
    client = relative_files(CLIENT_ROOT)
    errors: list[str] = []

    for relative in sorted(shared):
        owners = [
            name
            for name, files in (("server", server), ("client", client))
            if relative in files
        ]
        if owners:
            errors.append(
                f"shared module duplicated in role layer: {relative} owners={','.join(owners)}"
            )

    overlap = set(server).intersection(client)
    allowed_overlap = PACKAGE_ADAPTERS.union(overrides)
    for relative in sorted(overlap - allowed_overlap):
        errors.append(f"unregistered server/client overlap: {relative}")

    for relative in sorted(set(overrides) - overlap):
        errors.append(f"registered override missing from one role: {relative}")

    for relative in sorted(set(overrides).intersection(overlap)):
        if digest(server[relative]) == digest(client[relative]):
            errors.append(
                f"role override became identical and should move to shared_runtime: {relative}"
            )

    if errors:
        print("Runtime boundary check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        "Runtime boundary check passed: "
        f"shared_files={len(shared)} explicit_overrides={len(overrides)} "
        f"package_adapters={len(PACKAGE_ADAPTERS)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
