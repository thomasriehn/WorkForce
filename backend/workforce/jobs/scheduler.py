"""Scheduler-Prozess (genau eine aktive Instanz, abgesichert per PostgreSQL-Advisory-Sperre).

* Tageslauf zur konfigurierten lokalen Uhrzeit (Standard 03:15 Europe/Berlin); Zeitstempel in UTC.
* Sommer-/Winterzeit: maßgeblich ist das lokale Kalenderdatum; je Suchbereich und Datum genau ein Lauf.
* Neustart/verpasster Zeitpunkt: der Lauf des heutigen Tages wird nachgeholt (``catchup``). Vergangene
  Tage lassen sich nicht nachbeobachten und bleiben als Datenlücke sichtbar.
"""
from __future__ import annotations

import logging
import signal
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text as sql
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_engine, session_scope
from ..models import Job, ScanRun, SearchScope, Source
from ..pipeline.run import create_run
from . import queue

log = logging.getLogger("workforce.scheduler")
_stop = threading.Event()
LOCK_ID = 871002


def enqueue_run(db: Session, run: ScanRun, priority: int = 100) -> bool:
    job = queue.enqueue(db, "scan_run", {"run_id": run.id}, dedupe_key=f"scan:{run.id}", lock_key=f"source:{run.source_id}", priority=priority, max_attempts=3)
    return job is not None


def plan(db: Session, now: datetime | None = None, settings: Settings | None = None) -> dict[str, Any]:
    """Ein Planungsschritt (idempotent): fällige Tagesläufe, Folgejobs, verwaiste Jobs."""
    s = settings or get_settings()
    now = now or datetime.now(s.tz)
    local = now.astimezone(s.tz)
    today = local.date()
    out: dict[str, Any] = {"runs_created": 0, "jobs": 0, "recovered": queue.recover_stale(db, s.job_stale_after_seconds)}
    scan_at = datetime.combine(today, s.scan_time_local, tzinfo=s.tz)
    if local >= scan_at and s.crawler_contact.strip():
        late = local - scan_at > timedelta(hours=1)
        scopes = db.execute(select(SearchScope).join(Source, Source.id == SearchScope.source_id).where(
            SearchScope.is_active, Source.config_status == "active", Source.adapter_key.isnot(None))).scalars().all()
        for scope in scopes:
            run, created = create_run(db, scope, today, "catchup" if late else "scheduled")
            if created:
                out["runs_created"] += 1
    # Läufe ohne offenen Job einreihen (neu geplante, fortgesetzte, zur Wiederholung freigegebene)
    for run in db.execute(select(ScanRun).where(ScanRun.status == "queued")).scalars().all():
        if enqueue_run(db, run, priority=50 if run.trigger in ("manual", "test") else 100):
            out["jobs"] += 1
    # verwaiste „running“-Läufe ohne Job (z. B. nach hartem Neustart) kontrolliert fortsetzen
    for run in db.execute(select(ScanRun).where(ScanRun.status == "running")).scalars().all():
        open_job = db.execute(select(Job.id).where(Job.dedupe_key == f"scan:{run.id}", Job.status.in_(("queued", "running")))).first()
        if open_job is None and run.logical_date == today:
            if enqueue_run(db, run):
                out["jobs"] += 1
        elif open_job is None:
            run.status, run.status_detail, run.finished_at = "partial", "unterbrochen und nicht am selben Tag fortgesetzt", datetime.now(s.tz)
    stats_at = datetime.combine(today, s.stats_check_time_local, tzinfo=s.tz)
    if local >= stats_at:
        for kind, key in (("stats_check", f"stats:{today}"), ("maintenance", f"maintenance:{today}")):
            done = db.execute(select(Job.id).where(Job.dedupe_key == key)).first()
            if done is None and queue.enqueue(db, kind, {}, dedupe_key=key, lock_key=kind, priority=300, max_attempts=2):
                out["jobs"] += 1
    db.commit()
    return out


def main() -> None:
    from ..logging_setup import setup_logging

    setup_logging("workforce.scheduler")
    s = get_settings()
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    signal.signal(signal.SIGINT, lambda *_: _stop.set())
    lock_conn = get_engine().connect()
    try:
        while not _stop.is_set():
            if lock_conn.execute(sql("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}).scalar_one():
                break
            log.warning("ein anderer Scheduler ist aktiv – warte")
            _stop.wait(30)
        if not s.crawler_contact.strip():
            log.warning("WF_CRAWLER_CONTACT ist nicht gesetzt – es werden keine Scans geplant")
        while not _stop.is_set():
            try:
                with session_scope() as db:
                    result = plan(db)
                if result["runs_created"] or result["jobs"] or result["recovered"]:
                    log.info("Planung", extra=result)
            except Exception:  # noqa: BLE001
                log.exception("Planungsschritt fehlgeschlagen")
            _stop.wait(s.scheduler_tick_seconds)
    finally:
        lock_conn.close()
    log.info("Scheduler beendet")
