"""Betrieb: Aufbewahrung technischer Logs, Warnungen zu veralteten Quellen. Fachliche Historie wird nie gelöscht."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text as sql
from sqlalchemy.orm import Session

from .config import get_settings
from .models import OpsWarning, Source


def maintenance(db: Session) -> dict[str, Any]:
    s = get_settings()
    days = s.technical_log_retention_days
    out: dict[str, Any] = {}
    # nur technische Protokolle – Läufe, Beobachtungen, Versionen und Ereignisse bleiben erhalten
    out["scan_errors_deleted"] = db.execute(sql("DELETE FROM scan_error WHERE at < now() - make_interval(days => :d)"), {"d": days}).rowcount
    out["jobs_deleted"] = db.execute(sql("DELETE FROM job WHERE status IN ('done','failed','cancelled') AND finished_at < now() - make_interval(days => :d)"), {"d": days}).rowcount
    out["sessions_deleted"] = db.execute(sql("DELETE FROM user_session WHERE expires_at < now()")).rowcount
    out["fetch_cache_deleted"] = db.execute(sql("DELETE FROM fetch_cache WHERE fetched_at < now() - make_interval(days => :d)"), {"d": max(days, 30)}).rowcount
    out["warnings"] = check_stale_sources(db)
    db.flush()
    return out


def check_stale_sources(db: Session) -> int:
    s = get_settings()
    limit = datetime.now(UTC) - timedelta(hours=s.stale_source_warn_hours)
    n = 0
    for src in db.execute(select(Source).where(Source.config_status == "active")).scalars().all():
        last = db.execute(sql("SELECT max(finished_at) FROM scan_run WHERE source_id = :s AND NOT is_test AND status = 'complete'"), {"s": src.id}).scalar_one_or_none()
        key = f"stale:{src.id}"
        open_warning = db.execute(select(OpsWarning).where(OpsWarning.dedupe_key == key, OpsWarning.resolved_at.is_(None))).scalar_one_or_none()
        if last is None or last < limit:
            if open_warning is None:
                when = f"zuletzt {last:%d.%m.%Y %H:%M} UTC" if last else "noch nie"
                db.add(OpsWarning(kind="stale_source", dedupe_key=key, source_id=src.id,
                                  message=f"{src.name}: seit über {s.stale_source_warn_hours} Stunden kein vollständiger Lauf ({when})"))
                n += 1
        elif open_warning is not None:
            open_warning.resolved_at = datetime.now(UTC)
    return n
