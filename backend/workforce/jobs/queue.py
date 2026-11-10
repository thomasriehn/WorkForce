"""Persistente Jobverwaltung in PostgreSQL: Sperren (``FOR UPDATE SKIP LOCKED``), Wiederholungszähler,
Heartbeats und Wiederaufnahme verwaister Jobs. Kein Redis/Celery nötig."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text as sql
from sqlalchemy.orm import Session

from ..models import Job

_CLAIM_SQL = """
WITH next AS (
    SELECT j.id FROM job j
    WHERE j.status = 'queued' AND j.run_after <= now()
      AND (j.lock_key IS NULL OR NOT EXISTS (SELECT 1 FROM job r WHERE r.status = 'running' AND r.lock_key = j.lock_key))
    ORDER BY j.priority, j.id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE job SET status = 'running', locked_by = :worker, started_at = coalesce(job.started_at, now()),
               heartbeat_at = now(), attempts = job.attempts + 1
FROM next WHERE job.id = next.id
RETURNING job.id
"""


def enqueue(db: Session, kind: str, payload: dict[str, Any] | None = None, *, dedupe_key: str | None = None,
            lock_key: str | None = None, priority: int = 100, run_after: datetime | None = None, max_attempts: int = 3) -> Job | None:
    """Stellt einen Job ein. Mit ``dedupe_key`` höchstens ein offener Job gleicher Art (idempotent)."""
    if dedupe_key:
        open_job = db.execute(select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(("queued", "running")))).scalar_one_or_none()
        if open_job is not None:
            return None
    job = Job(kind=kind, payload=payload or {}, dedupe_key=dedupe_key, lock_key=lock_key, priority=priority,
              run_after=run_after or datetime.now(UTC), max_attempts=max_attempts)
    db.add(job)
    db.flush()
    return job


def claim(db: Session, worker_id: str) -> int | None:
    """Übernimmt den nächsten ausführbaren Job; Jobs mit gleichem ``lock_key`` laufen nie parallel."""
    db.execute(sql("SELECT pg_advisory_xact_lock(871001)"))  # serialisiert die Auswahl (kurz)
    job_id = db.execute(sql(_CLAIM_SQL), {"worker": worker_id}).scalar_one_or_none()
    db.commit()
    return job_id


def heartbeat(db: Session, job_id: int) -> None:
    db.execute(sql("UPDATE job SET heartbeat_at = now() WHERE id = :id AND status = 'running'"), {"id": job_id})
    db.commit()


def finish(db: Session, job_id: int, *, ok: bool, result: dict[str, Any] | None = None, error: str | None = None, retry: bool = True) -> str:
    job = db.get(Job, job_id, populate_existing=True)  # Zähler stammen aus SQL-Updates – nie aus dem Sitzungscache
    if job is None:
        return "missing"
    now = datetime.now(UTC)
    if ok:
        job.status, job.result, job.finished_at, job.last_error = "done", result, now, None
    else:
        job.last_error = (error or "")[:4000]
        if retry and job.attempts < job.max_attempts:
            job.status, job.locked_by = "queued", None
            job.run_after = now + timedelta(minutes=5 * job.attempts)
        else:
            job.status, job.finished_at = "failed", now
    db.commit()
    return job.status


def recover_stale(db: Session, stale_after_seconds: int) -> int:
    """Verwaiste Jobs (Worker abgestürzt/neu gestartet) kontrolliert wieder einreihen oder beenden."""
    rows = db.execute(sql(
        "UPDATE job SET status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END, "
        "locked_by = NULL, last_error = coalesce(last_error, '') || ' [verwaist: kein Heartbeat]', "
        "finished_at = CASE WHEN attempts < max_attempts THEN NULL ELSE now() END "
        "WHERE status = 'running' AND heartbeat_at < now() - make_interval(secs => :s) RETURNING id"),
        {"s": stale_after_seconds}).all()
    db.commit()
    return len(rows)
