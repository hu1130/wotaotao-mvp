"""Process entrypoint for the durable person-memory worker."""

from __future__ import annotations

import logging
import signal

from core.person_memory.worker import PersonMemoryWorker


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    worker = PersonMemoryWorker()

    def handle_signal(signum, frame) -> None:
        logging.getLogger(__name__).info("人物记忆 worker 收到退出信号: %s", signum)
        worker.stop()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, handle_signal)
    try:
        worker.run_forever()
    finally:
        worker.close()


if __name__ == "__main__":
    main()
