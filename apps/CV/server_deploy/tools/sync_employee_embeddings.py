"""Sync local employee photos into the pgvector employee embedding store."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.face_db import FaceDatabase
from core.vector_db import VectorDB


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract employees/* face embeddings and upsert them to pgvector."
    )
    parser.parse_args()

    db = FaceDatabase()
    db.build(force=True)
    embeddings = VectorDB().get_all_embeddings()
    people = sorted({name for name, _ in embeddings})
    print(
        json.dumps(
            {
                "ok": True,
                "employees": people,
                "employeeCount": len(people),
                "embeddingCount": len(embeddings),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
