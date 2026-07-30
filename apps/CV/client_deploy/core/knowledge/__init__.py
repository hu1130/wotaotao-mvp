"""Local knowledge base retrieval and grounded answering."""

from pathlib import Path

for _parent in Path(__file__).resolve().parents:
    _candidate = _parent / "shared_runtime" / "core" / "knowledge"
    if _candidate.is_dir():
        if str(_candidate) not in __path__:
            __path__.append(str(_candidate))
        break

from core.knowledge.service import KnowledgeService

__all__ = ["KnowledgeService"]

del _candidate, _parent, Path
