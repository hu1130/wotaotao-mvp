"""Run the FastAPI company integration service."""

from __future__ import annotations

import logging

import uvicorn

from config import API_HOST, API_PORT, API_WORKERS


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if API_WORKERS != 1:
        raise RuntimeError(
            "API_WORKERS>1 is intentionally blocked until person sessions and "
            "recognition trajectory state use a cross-process store; scale by "
            "tenant/device-partitioned API instances instead"
        )
    uvicorn.run(
        "api.main:app",
        host=API_HOST,
        port=API_PORT,
        workers=API_WORKERS,
        reload=False,
    )


if __name__ == "__main__":
    main()
