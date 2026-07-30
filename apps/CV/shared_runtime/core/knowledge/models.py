"""Data structures for local knowledge retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceDocument:
    source_path: str
    title: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeChunk:
    source_path: str
    title: str
    content: str
    chunk_index: int
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    chunk_id: int
    source_path: str
    title: str
    content: str
    score: float
    chunk_index: int
    metadata: dict[str, str] = field(default_factory=dict)

    def citation_label(self) -> str:
        title = self.title or self.source_path
        return f"{title}#{self.chunk_index + 1}"
