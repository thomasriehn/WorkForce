"""Worker-Prozess: arbeitet Jobs aus der PostgreSQL-Queue ab (ein Thread je parallelem Job)."""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from ..config import get_settings
from ..db import session_scope
from ..models import Job, ScanRun
from . import queue

log = logging.getLogger("workforce.worker")
_stop = threading.Event()


def _h_scan_run(payload: dict[str, Any], beat: Callable[[], None]) -> dict[str, Any]:
    from ..pipeline.run import RunRefused, execute_run

    run_id = int(payload["run_id"])
    try:
        status = execute_run(run_id, heartbeat=beat)
    except RunRefused as exc:
        return {"run_id": run_id, "status": "refused", "detail": str(exc)}
    with session_scope() as db:
        run = db.get(ScanRun, run_id)
        if run is not None and not run.is_test and status in ("complete", "partial"):
            queue.enqueue(db, "aggregate", {"date": run.logical_date.isoformat()}, dedupe_key=f"aggregate:{run.logical_date}", lock_key="aggregate", priority=200)
    return {"run_id": run_id, "status": status}


def _h_aggregate(payload: dict[str, Any], beat: Callable[[], None]) -> dict[str, Any]:
    from ..pipeline import aggregate

    with session_scope() as db:
        if payload.get("from") and payload.get("to"):
            return aggregate.compute_range(db, date.fromisoformat(payload["from"]), date.fromisoformat(payload["to"]))
        today = date.fromisoformat(payload["date"]) if payload.get("date") else datetime.now(get_settings().tz).date()
        return aggregate.nightly(db, today)


def _h_stats_check(payload: dict[str, Any], beat: Callable[[], None]) -> dict[str, Any]:
    from ..stats.runner import run_imports

    return run_imports(payload.get("datasets"), heartbeat=beat)


def _h_maintenance(payload: dict[str, Any], beat: Callable[[], None]) -> dict[str, Any]:
    from ..ops import maintenance

    with session_scope() as db:
        return maintenance(db)


def _h_geo_rematch(payload: dict[str, Any], beat: Callable[[], None]) -> dict[str, Any]:
    from ..pipeline.ingest import classify_missing_occupations, rematch_unresolved

    with session_scope() as db:
        return {"rematched_versions": rematch_unresolved(db), "classified_versions": classify_missing_occupations(db)}


HANDLERS: dict[str, Callable[[dict[str, Any], Callable[[], None]], dict[str, Any]]] = {
    "scan_run": _h_scan_run, "aggregate": _h_aggregate, "stats_check": _h_stats_check, "maintenance": _h_maintenance, "geo_rematch": _h_geo_rematch,
}


def process_one(worker_id: str) -> bool:
    """Übernimmt und bearbeitet höchstens einen Job. Gibt False zurück, wenn nichts anstand."""
    s = get_settings()
    with session_scope() as db:
        job_id = queue.claim(db, worker_id)
        if job_id is None:
            return False
        job = db.get(Job, job_id)
        assert job is not None
        kind, payload = job.kind, dict(job.payload or {})
    last_beat = [0.0]

    def beat() -> None:
        if time.monotonic() - last_beat[0] >= s.job_heartbeat_seconds:
            last_beat[0] = time.monotonic()
            with session_scope() as hb:
                queue.heartbeat(hb, job_id)

    done = threading.Event()

    def ticker() -> None:  # Heartbeat auch während langer Wartezeiten (Abrufabstände, Backoff)
        while not done.wait(s.job_heartbeat_seconds):
            try:
                with session_scope() as hb:
                    queue.heartbeat(hb, job_id)
            except Exception:  # noqa: BLE001
                log.exception("Heartbeat fehlgeschlagen")

    threading.Thread(target=ticker, daemon=True).start()
    started = time.monotonic()
    try:
        handler = HANDLERS.get(kind)
        if handler is None:
            raise RuntimeError(f"unbekannte Jobart {kind!r}")
        result = handler(payload, beat)
        with session_scope() as db:
            queue.finish(db, job_id, ok=True, result=result)
        log.info("Job erledigt", extra={"job_id": job_id, "kind": kind, "seconds": round(time.monotonic() - started, 1), "result": result})
    except Exception as exc:  # noqa: BLE001 – Fehler gehören sichtbar in die Jobtabelle
        log.exception("Job fehlgeschlagen", extra={"job_id": job_id, "kind": kind})
        with session_scope() as db:
            status = queue.finish(db, job_id, ok=False, error=f"{type(exc).__name__}: {exc}")
            if status == "failed" and kind == "scan_run":
                run = db.get(ScanRun, int(payload.get("run_id", 0)))
                if run is not None and run.status in ("queued", "running"):
                    run.status, run.status_detail, run.finished_at = "failed", f"Job endgültig fehlgeschlagen: {exc}"[:500], datetime.now().astimezone()
    finally:
        done.set()
    return True


def _loop(worker_id: str) -> None:
    while not _stop.is_set():
        try:
            if not process_one(worker_id):
                _stop.wait(3.0)
        except Exception:  # noqa: BLE001
            log.exception("Worker-Schleife: unerwarteter Fehler")
            _stop.wait(5.0)


def main() -> None:
    from ..logging_setup import setup_logging

    setup_logging("workforce.worker")
    s = get_settings()
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    base = f"{socket.gethostname()}:{os.getpid()}"
    threads = [threading.Thread(target=_loop, args=(f"{base}:{i}",), name=f"worker-{i}") for i in range(max(1, s.worker_concurrency))]

    def alive() -> None:  # Lebenszeichen unabhängig von lang laufenden Jobs
        from ..ops import beat

        while not _stop.is_set():
            try:
                beat("worker")
            except Exception:  # noqa: BLE001
                log.exception("Lebenszeichen fehlgeschlagen")
            _stop.wait(30)

    threading.Thread(target=alive, daemon=True, name="worker-alive").start()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log.info("Worker beendet")
