"""InsightFace application factory."""

from __future__ import annotations

from insightface.app import FaceAnalysis

from config import (
    DETECTION_THRESHOLD,
    INSIGHTFACE_DET_SIZE,
    INSIGHTFACE_MODEL,
    INSIGHTFACE_PROVIDERS,
    INSIGHTFACE_ROOT,
)


def create_face_analysis() -> FaceAnalysis:
    app = FaceAnalysis(
        name=INSIGHTFACE_MODEL,
        root=INSIGHTFACE_ROOT,
        allowed_modules=["detection", "recognition", "genderage"],
        providers=INSIGHTFACE_PROVIDERS,
    )
    app.prepare(
        ctx_id=0,
        det_thresh=DETECTION_THRESHOLD,
        det_size=INSIGHTFACE_DET_SIZE,
    )
    return app
