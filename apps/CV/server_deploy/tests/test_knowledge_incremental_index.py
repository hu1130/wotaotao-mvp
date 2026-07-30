from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.knowledge.models import SourceDocument
from core.knowledge.service import KnowledgeService
from core.tenant import DEFAULT_TENANT_ID


class FakeKnowledgeStore:
    def __init__(self, fingerprints: dict[str, dict[str, object]]) -> None:
        self.fingerprints = fingerprints
        self.deleted_request: tuple[list[str], list[str]] | None = None
        self.upserted_chunks = []
        self.document_metadata = {}

    def reset(self) -> None:
        raise AssertionError("incremental index must not reset")

    def get_document_fingerprints(self, source_paths: list[str]) -> dict[str, dict[str, object]]:
        return {
            source_path: self.fingerprints[source_path]
            for source_path in source_paths
            if source_path in self.fingerprints
        }

    def delete_missing_sources(
        self,
        *,
        active_source_paths: list[str],
        scope_paths: list[str],
    ) -> int:
        self.deleted_request = (active_source_paths, scope_paths)
        return 0

    def upsert_chunks(self, chunks, *, document_metadata=None) -> int:
        self.upserted_chunks = list(chunks)
        self.document_metadata = dict(document_metadata or {})
        return len(chunks)

    def stats(self) -> dict:
        return {"documents": 2, "chunks": len(self.upserted_chunks)}


class KnowledgeIncrementalIndexTest(unittest.TestCase):
    def test_incremental_index_skips_unchanged_documents_before_loading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unchanged = root / "unchanged.md"
            changed = root / "changed.md"
            unchanged.write_text("unchanged content", encoding="utf-8")
            changed.write_text("changed content", encoding="utf-8")

            service = KnowledgeService.__new__(KnowledgeService)
            service.tenant_id = DEFAULT_TENANT_ID
            unchanged_fingerprint = KnowledgeService._file_fingerprint(unchanged)
            service.store = FakeKnowledgeStore(
                {str(unchanged.resolve()): unchanged_fingerprint}
            )

            loaded_paths: list[str] = []

            def fake_load_document(path: str | Path) -> SourceDocument:
                resolved = str(Path(path).resolve())
                loaded_paths.append(resolved)
                return SourceDocument(
                    source_path=resolved,
                    title=Path(path).stem,
                    content="changed content",
                    metadata={"extension": ".md"},
                )

            with patch.object(KnowledgeService, "_validate_path", lambda _, value: str(Path(value).resolve())):
                with patch("core.knowledge.service.load_document", fake_load_document):
                    result = service.index_paths([str(root)], reset=False)

            self.assertEqual(loaded_paths, [str(changed.resolve())])
            self.assertEqual(result["documents"], 2)
            self.assertEqual(result["indexedDocuments"], 1)
            self.assertEqual(result["skippedDocuments"], 1)
            self.assertEqual(result["removedDocuments"], 0)
            self.assertEqual(len(service.store.upserted_chunks), 1)
            self.assertIn(str(changed.resolve()), service.store.document_metadata)
            self.assertIsNotNone(service.store.deleted_request)


if __name__ == "__main__":
    unittest.main()
