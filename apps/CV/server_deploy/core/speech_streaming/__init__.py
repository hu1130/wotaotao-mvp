"""Streaming speech pipeline providers."""

from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    _candidate = _parent / "shared_runtime" / "core" / "speech_streaming"
    if _candidate.is_dir():
        if str(_candidate) not in __path__:
            __path__.append(str(_candidate))
        break

del _candidate, _parent, Path
