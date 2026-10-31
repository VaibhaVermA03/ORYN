"""Database-backed ingestion worker.

PostgreSQL is the queue: documents in `uploaded` state are claimed with
`SELECT ... FOR UPDATE SKIP LOCKED`, so any number of workers can run safely and a crash never
loses work (stale claims are recovered). Run it either inline in the API process
(INGESTION_WORKER_MODE=inline, the default) or as a dedicated service:

    python -m app.workers.ingestion_worker

Limitations: throughput is bounded by worker count and provider rate limits; there is no
priority or per-tenant fairness. To scale further, replace `claim_next_document` with a
broker-backed queue (e.g. Redis/Celery or SQS) -- `process_document` is already idempotent.
"""

from __future__ import annotations

import logging
import signal
import threading
import time

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.ingestion_service import claim_next_document, process_document, recover_stale_documents

logger = logging.getLogger("oryn.worker")

_wake = threading.Event()


def wake_worker() -> None:
    """Nudge an in-process worker after an upload so processing starts immediately."""
    _wake.set()


class IngestionWorker(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="oryn-ingestion-worker", daemon=True)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()
        _wake.set()

    def run(self) -> None:
        s = get_settings()
        last_recovery = 0.0
        logger.info("worker_started")
        while not self._stop_event.is_set():
            try:
                if time.monotonic() - last_recovery > 60:
                    recovered = recover_stale_documents()
                    if recovered:
                        logger.warning("recovered_stale_documents", extra={"count": recovered})
                    last_recovery = time.monotonic()
                doc_id = claim_next_document()
                if doc_id is None:
                    _wake.wait(timeout=s.ingestion_worker_poll_seconds)
                    _wake.clear()
                    continue
                process_document(doc_id)
            except Exception:  # noqa: BLE001 - the loop must survive any single failure
                logger.exception("worker_iteration_failed")
                self._stop_event.wait(5)
        logger.info("worker_stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.validate_runtime()
    worker = IngestionWorker()
    signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    signal.signal(signal.SIGINT, lambda *_: worker.stop())
    worker.start()
    worker.join()


if __name__ == "__main__":
    main()
