"""Employee photo embedding sync into pgvector.

Runtime recognition reads employee embeddings from pgvector into memory. This
module exists only for explicit sync/rebuild operations from local photos.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import cv2
from insightface.app import FaceAnalysis

from config import EMPLOYEES_DIR, TENANT_ID
from core.employee_names import normalize_employee_name
from core.insightface_factory import create_face_analysis
from core.tenant import normalize_tenant_id
from core.vector_db import VectorDB

logger = logging.getLogger(__name__)


class FaceDatabase:
    """Syncs local employee photos to the pgvector employee embedding store."""

    def __init__(self, app: FaceAnalysis | None = None):
        self._app = app
        self._embeddings: list[tuple[str, object]] = []

    def _get_app(self) -> FaceAnalysis:
        if self._app is None:
            logger.info("正在初始化 InsightFace 模型用于同步员工照片...")
            self._app = create_face_analysis()
        return self._app

    def build(self, force: bool = False) -> None:
        """Extract local employee photo embeddings and upsert them to pgvector."""
        app = self._get_app()
        vector_db = VectorDB()
        self._embeddings = []

        tenant_id = normalize_tenant_id(TENANT_ID)
        tenant_root = (Path(EMPLOYEES_DIR).expanduser().resolve() / tenant_id).resolve()
        if not tenant_root.is_dir():
            logger.warning("当前租户 employees 目录不存在，跳过员工照片同步: tenant=%s", tenant_id)
            return

        synced_people = 0
        synced_vectors = 0
        for raw_name in sorted(os.listdir(tenant_root)):
            try:
                employee_name = normalize_employee_name(raw_name)
            except ValueError:
                logger.warning("跳过不安全的员工目录名: tenant=%s name=%r", tenant_id, raw_name)
                continue
            employee_dir = os.path.join(tenant_root, employee_name)
            if not os.path.isdir(employee_dir):
                continue

            vectors = []
            for filename in sorted(os.listdir(employee_dir)):
                if not filename.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
                    continue
                img_path = os.path.join(employee_dir, filename)
                embedding = self._extract_embedding(app, img_path)
                if embedding is None:
                    continue
                vectors.append((embedding, "local", img_path))
                self._embeddings.append((employee_name, embedding))
                logger.info("  提取特征: %s / %s", employee_name, filename)

            if vectors:
                vector_db.upsert_employee(employee_name, vectors, tenant_id)
                synced_people += 1
                synced_vectors += len(vectors)
                logger.info("pgvector 同步完成: %s (%d 条向量)", employee_name, len(vectors))

        logger.info(
            "员工照片同步完成: tenant=%s people=%d vectors=%d",
            tenant_id,
            synced_people,
            synced_vectors,
        )

    def _extract_embedding(self, app: FaceAnalysis, img_path: str):
        img = cv2.imread(img_path)
        if img is None:
            logger.warning("无法读取图片: %s", img_path)
            return None
        faces = app.get(img)
        if len(faces) == 0:
            logger.warning("未检测到人脸: %s", img_path)
            return None
        face = max(faces, key=lambda item: float(item.det_score))
        return face.normed_embedding

    def get_all(self):
        return VectorDB().get_all_embeddings(normalize_tenant_id(TENANT_ID))

    def __len__(self) -> int:
        return len(self.get_all())
