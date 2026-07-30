"""Text chunking for knowledge retrieval."""

from __future__ import annotations

import re

from core.knowledge.models import KnowledgeChunk, SourceDocument


def chunk_document(
    document: SourceDocument,
    chunk_size: int,
    overlap: int,
) -> list[KnowledgeChunk]:
    chunk_size = max(200, chunk_size)
    overlap = max(0, min(overlap, chunk_size // 2))
    sections = _split_sections(document.content)
    chunks: list[KnowledgeChunk] = []

    current = ""
    for section in sections:
        if not current:
            current = section
            continue
        if len(current) + len(section) + 2 <= chunk_size:
            current = f"{current}\n\n{section}"
            continue
        chunks.extend(_split_large_text(document, current, len(chunks), chunk_size, overlap))
        current = section

    if current:
        chunks.extend(_split_large_text(document, current, len(chunks), chunk_size, overlap))
    return chunks


def _split_sections(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return parts or [text.strip()]


def _split_large_text(
    document: SourceDocument,
    text: str,
    start_index: int,
    chunk_size: int,
    overlap: int,
) -> list[KnowledgeChunk]:
    if len(text) <= chunk_size:
        return [
            KnowledgeChunk(
                source_path=document.source_path,
                title=document.title,
                content=text,
                chunk_index=start_index,
                metadata=document.metadata,
            )
        ]

    chunks: list[KnowledgeChunk] = []
    cursor = 0
    while cursor < len(text):
        end = min(len(text), cursor + chunk_size)
        if end < len(text):
            boundary = max(
                text.rfind("\n", cursor, end),
                text.rfind("。", cursor, end),
                text.rfind("；", cursor, end),
                text.rfind(".", cursor, end),
            )
            if boundary > cursor + chunk_size // 2:
                end = boundary + 1
        content = text[cursor:end].strip()
        if content:
            chunks.append(
                KnowledgeChunk(
                    source_path=document.source_path,
                    title=document.title,
                    content=content,
                    chunk_index=start_index + len(chunks),
                    metadata=document.metadata,
                )
            )
        if end >= len(text):
            break
        cursor = max(end - overlap, cursor + 1)
    return chunks
