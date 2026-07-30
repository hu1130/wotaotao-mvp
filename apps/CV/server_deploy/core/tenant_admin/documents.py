"""Tenant-scoped managed knowledge document filesystem."""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path
from typing import BinaryIO

from config import KNOWLEDGE_BASE_DIR, TENANT_ADMIN_DOCUMENT_MAX_BYTES
from core.knowledge.loaders import SUPPORTED_EXTENSIONS
from core.tenant import normalize_tenant_id


class TenantKnowledgeDocumentService:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = normalize_tenant_id(tenant_id)
        self.root = (
            Path(KNOWLEDGE_BASE_DIR) / "tenants" / self.tenant_id / "managed"
        ).resolve()

    def list_documents(self) -> list[dict[str, object]]:
        if not self.root.exists():
            return []
        documents = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            stat = path.stat()
            documents.append(
                {
                    "name": path.name,
                    "relativePath": path.relative_to(self.root).as_posix(),
                    "extension": path.suffix.lower(),
                    "size": stat.st_size,
                    "modifiedAt": stat.st_mtime,
                }
            )
        return documents

    def save(self, filename: str, source: BinaryIO) -> dict[str, object]:
        safe_name = self._safe_filename(filename)
        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ValueError(f"不支持的文档类型 {suffix or '(无扩展名)'}；支持: {allowed}")
        self.root.mkdir(parents=True, exist_ok=True)
        target = (self.root / safe_name).resolve()
        self._assert_inside_root(target)
        temporary = target.with_name(
            f".{target.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
        )
        total = 0
        try:
            with temporary.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max(1, int(TENANT_ADMIN_DOCUMENT_MAX_BYTES)):
                        raise ValueError("单个企业文档超过允许大小")
                    output.write(chunk)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return {
            "name": target.name,
            "relativePath": target.relative_to(self.root).as_posix(),
            "extension": suffix,
            "size": total,
            "modifiedAt": target.stat().st_mtime,
        }

    def delete(self, relative_path: str) -> bool:
        normalized = str(relative_path or "").replace("\\", "/").lstrip("/")
        target = (self.root / normalized).resolve()
        self._assert_inside_root(target)
        if not target.is_file():
            return False
        target.unlink()
        return True

    def _assert_inside_root(self, path: Path) -> None:
        if path != self.root and self.root not in path.parents:
            raise ValueError("文档路径越出租户目录")

    @staticmethod
    def _safe_filename(filename: str) -> str:
        value = str(filename or "").replace("\\", "/").split("/")[-1].strip()
        value = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", value)
        value = value.strip(". ")
        if not value:
            raise ValueError("文档文件名为空")
        if len(value) > 180:
            suffix = Path(value).suffix
            value = value[: max(1, 180 - len(suffix))] + suffix
        return value
