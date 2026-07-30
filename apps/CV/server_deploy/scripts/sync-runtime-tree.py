"""Synchronize a deployment source tree without requiring rsync."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def normalized_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_preserved(relative: str, preserved: tuple[str, ...]) -> bool:
    return any(relative == prefix or relative.startswith(f"{prefix}/") for prefix in preserved)


def validate_paths(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"source directory does not exist: {source}")
    if source == destination:
        raise ValueError("source and destination must differ")
    if destination == Path(destination.anchor):
        raise ValueError(f"refusing to synchronize into filesystem root: {destination}")
    if source in destination.parents:
        raise ValueError(f"destination cannot be inside source: {destination}")
    if destination in source.parents:
        raise ValueError(f"source cannot be inside destination: {source}")


def source_files(root: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = normalized_relative(path, root)
        if "__pycache__" in path.parts or relative.endswith((".pyc", ".pyo")):
            continue
        files[relative] = path
    return files


def synchronize(source: Path, destination: Path, preserved: tuple[str, ...]) -> None:
    validate_paths(source, destination)
    destination.mkdir(parents=True, exist_ok=True)
    files = source_files(source)
    copied = 0
    removed = 0

    for relative, source_path in files.items():
        target = destination / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        copied += 1

    for target in sorted(destination.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        relative = normalized_relative(target, destination)
        if is_preserved(relative, preserved):
            continue
        if target.is_file() or target.is_symlink():
            if relative not in files:
                target.unlink()
                removed += 1
        elif target.is_dir():
            try:
                target.rmdir()
            except OSError:
                pass

    print(
        "runtime tree synchronized: "
        f"source={source} destination={destination} copied={copied} removed={removed} "
        f"preserved={','.join(preserved) or '(none)'}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument(
        "--preserve",
        action="append",
        default=[],
        help="Relative file or directory prefix to retain when absent from source",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    destination = Path(args.destination).expanduser().resolve()
    preserved = tuple(
        sorted({str(value).strip().strip("/\\").replace("\\", "/") for value in args.preserve if str(value).strip()})
    )
    synchronize(source, destination, preserved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
