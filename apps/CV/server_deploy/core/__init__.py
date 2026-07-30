"""Server-specific core package overlaid on the repository shared runtime."""

from pathlib import Path


def _extend_shared_core_path() -> None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "shared_runtime" / "core"
        if candidate.is_dir():
            candidate_text = str(candidate)
            if candidate_text not in __path__:
                __path__.append(candidate_text)
            return


_extend_shared_core_path()
del _extend_shared_core_path, Path
